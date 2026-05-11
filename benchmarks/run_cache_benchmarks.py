#!/usr/bin/env python3
"""Run ofort cache benchmarks with and without --cache."""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from pathlib import Path


BENCHMARKS = [
    "xbench_cached_integer_arith.f90",
    "xbench_cached_index_expr.f90",
    "xbench_cached_repeated_runs.f90",
]

TIME_RE = re.compile(r"^\s*(setup|lex|parse|register|execute|total):\s+([0-9.]+)\s+s\s*$")
REPL_TIME_RE = re.compile(
    r"^total\s+([0-9.]+)\s+avg\s+([0-9.]+)\s+min\s+([0-9.]+)\s+max\s+([0-9.]+)\s*$"
)
REPL_TIME_TABLE_RE = re.compile(
    r"^\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+s\s*$"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_times(text: str) -> dict[str, float]:
    times: dict[str, float] = {}
    for line in text.splitlines():
        match = TIME_RE.match(line)
        if match:
            times[match.group(1)] = float(match.group(2))
    return times


def run_one(ofort: Path, source: Path, use_cache: bool, repeat: int) -> dict[str, float | str]:
    totals: list[float] = []
    executes: list[float] = []
    parses: list[float] = []
    cmd_base = [str(ofort), "--fast"]
    if use_cache:
        cmd_base.append("--cache")
    cmd_base.extend([str(source), "--time-detail"])

    for _ in range(repeat):
        result = subprocess.run(
            cmd_base,
            cwd=repo_root(),
            text=True,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "total": 0.0,
                "execute": 0.0,
                "parse": 0.0,
                "stderr": result.stderr.strip(),
            }
        times = parse_times(result.stdout + "\n" + result.stderr)
        if "total" not in times or "execute" not in times:
            return {
                "status": "bad-output",
                "total": 0.0,
                "execute": 0.0,
                "parse": 0.0,
                "stderr": "could not parse --time-detail output",
            }
        totals.append(times["total"])
        executes.append(times["execute"])
        parses.append(times.get("parse", 0.0))

    return {
        "status": "ok",
        "total": statistics.mean(totals),
        "execute": statistics.mean(executes),
        "parse": statistics.mean(parses),
        "stderr": "",
    }


def parse_repl_time(text: str) -> dict[str, float]:
    for line in text.splitlines():
        match = REPL_TIME_RE.match(line.strip())
        if match:
            return {
                "total": float(match.group(1)),
                "avg": float(match.group(2)),
                "min": float(match.group(3)),
                "max": float(match.group(4)),
            }
        match = REPL_TIME_TABLE_RE.match(line.strip())
        if match:
            return {
                "total": float(match.group(1)),
                "avg": float(match.group(2)),
                "min": float(match.group(4)),
                "max": float(match.group(5)),
            }
    return {}


def run_repl_time(ofort: Path, source: Path, use_cache: bool, time_repeat: int) -> dict[str, float | str]:
    cmd = [str(ofort), "--fast", "--repl", "--nologo", "--prompt", ">"]
    if use_cache:
        cmd.append("--cache")
    commands = source.read_text(encoding="utf-8")
    if not commands.endswith("\n"):
        commands += "\n"
    commands += f".time {time_repeat}\n.quit!\n"
    result = subprocess.run(
        cmd,
        cwd=repo_root(),
        input=commands,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        return {
            "status": "failed",
            "total": 0.0,
            "avg": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stderr": result.stderr.strip(),
        }
    times = parse_repl_time(result.stdout + "\n" + result.stderr)
    if not times:
        return {
            "status": "bad-output",
            "total": 0.0,
            "avg": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stderr": "could not parse REPL .time output",
        }
    return {
        "status": "ok",
        "total": times["total"],
        "avg": times["avg"],
        "min": times["min"],
        "max": times["max"],
        "stderr": "",
    }


def print_process_table(ofort: Path, repeat: int) -> int:
    root = repo_root()
    print("process mode: starts a new ofort.exe for each run")
    print()
    print(
        f"{'benchmark':34} {'mode':9} {'total_s':>10} {'execute_s':>10} "
        f"{'parse_s':>9} {'speedup':>8} {'status':>10}"
    )
    print("-" * 96)

    overall_status = 0
    for name in BENCHMARKS:
        source = root / "benchmarks" / name
        no_cache = run_one(ofort, source, False, repeat)
        cache = run_one(ofort, source, True, repeat)
        if no_cache["status"] != "ok" or cache["status"] != "ok":
            overall_status = 1

        base_total = float(no_cache["total"])
        for mode, row in (("no-cache", no_cache), ("cache", cache)):
            total = float(row["total"])
            speedup = base_total / total if total > 0.0 and row["status"] == "ok" else 0.0
            print(
                f"{name:34} {mode:9} {total:10.4f} {float(row['execute']):10.4f} "
                f"{float(row['parse']):9.4f} {speedup:8.2f} {str(row['status']):>10}"
            )
            if row["status"] != "ok" and row["stderr"]:
                print(f"  {row['stderr']}")
    return overall_status


def print_repl_table(ofort: Path, time_repeat: int) -> int:
    root = repo_root()
    print("repl mode: one ofort.exe per benchmark; .load source, then .time n")
    print()
    print(
        f"{'benchmark':34} {'mode':9} {'total_s':>10} {'avg_s':>10} "
        f"{'min_s':>10} {'max_s':>10} {'speedup':>8} {'status':>10}"
    )
    print("-" * 108)

    overall_status = 0
    for name in BENCHMARKS:
        source = root / "benchmarks" / name
        no_cache = run_repl_time(ofort, source, False, time_repeat)
        cache = run_repl_time(ofort, source, True, time_repeat)
        if no_cache["status"] != "ok" or cache["status"] != "ok":
            overall_status = 1

        base_avg = float(no_cache["avg"])
        for mode, row in (("no-cache", no_cache), ("cache", cache)):
            avg = float(row["avg"])
            speedup = base_avg / avg if avg > 0.0 and row["status"] == "ok" else 0.0
            print(
                f"{name:34} {mode:9} {float(row['total']):10.4f} {avg:10.4f} "
                f"{float(row['min']):10.4f} {float(row['max']):10.4f} "
                f"{speedup:8.2f} {str(row['status']):>10}"
            )
            if row["status"] != "ok" and row["stderr"]:
                print(f"  {row['stderr']}")
    return overall_status


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ofort", type=Path, default=repo_root() / "ofort.exe")
    parser.add_argument("--repeat", type=int, default=3, help="runs per mode")
    parser.add_argument(
        "--mode",
        choices=("process", "repl", "both"),
        default="both",
        help="benchmark process-level cache, in-process REPL cache, or both",
    )
    parser.add_argument(
        "--time-repeat",
        type=int,
        default=3,
        help="repeat count passed to REPL .time in --mode repl/both",
    )
    args = parser.parse_args(argv)

    ofort = args.ofort
    if not ofort.exists():
        print(f"ofort executable not found: {ofort}", file=sys.stderr)
        return 2
    if args.repeat < 1:
        print("--repeat must be at least 1", file=sys.stderr)
        return 2
    if args.time_repeat < 1:
        print("--time-repeat must be at least 1", file=sys.stderr)
        return 2

    print(f"ofort: {ofort}")
    print(f"process repeat: {args.repeat}")
    print(f"repl .time repeat: {args.time_repeat}")
    print()
    overall_status = 0
    if args.mode in ("process", "both"):
        overall_status |= print_process_table(ofort, args.repeat)
    if args.mode == "both":
        print()
    if args.mode in ("repl", "both"):
        overall_status |= print_repl_table(ofort, args.time_repeat)

    return overall_status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
