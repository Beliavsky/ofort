#!/usr/bin/env python3
"""Run benchmark programs with ofort, gfortran, ifx, and lfortran.

The script stores one row per benchmark/task in a pandas DataFrame and writes it
to CSV by default.  Toggle the RUN_* values below, or use the --no-* command-line
options, to disable tools that are unavailable on a machine.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_GLOB = str(ROOT / "benchmarks" / "*.f90")
DEFAULT_OUTPUT = ROOT / "benchmarks" / "benchmark_results.csv"
DEFAULT_OFORT = ROOT / ("ofort.exe" if sys.platform.startswith("win") else "ofort")
BENCHMARK_METADATA_NAME = "benchmark_parameters.json"

# Easy script-level switches.
RUN_OFORT = True
RUN_OFORT_FAST = True
RUN_GFORTRAN = True
RUN_IFX = True
RUN_LFORTRAN = True

# Compiler option sets used for the compiled-code comparisons.
GFORTRAN_OPTIONS = ["-O3", "-march=native"]
IFX_OPTIONS = ["/O3", "/QxHost", "/fp:precise"]
LFORTRAN_OPTIONS = ["--fast"]

pd = None


def require_pandas():
    global pd
    if pd is None:
        try:
            import pandas as pandas_module
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise SystemExit("bench_ofort.py requires pandas: python -m pip install pandas") from exc
        pd = pandas_module
    return pd


@dataclass
class Task:
    name: str
    enabled: bool
    kind: str
    executable: str
    options: list[str]
    version: str


def expand_patterns(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if not matches and Path(pattern).exists():
            matches = [pattern]
        for match in sorted(matches):
            path = Path(match)
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(resolved)
    return files


def benchmark_metadata_path(sources: list[Path]) -> Path | None:
    if not sources:
        return None
    directories = {source.parent for source in sources}
    if len(directories) != 1:
        return None
    path = next(iter(directories)) / BENCHMARK_METADATA_NAME
    return path if path.exists() else None


def print_benchmark_parameters(sources: list[Path]) -> None:
    path = benchmark_metadata_path(sources)
    if not path:
        print("benchmark parameters: not found; run scripts\\generate_benchmarks.py to record them")
        return
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"benchmark parameters: could not read {path}: {exc}")
        return
    size = metadata.get("size", "unknown")
    generator = metadata.get("generator", "unknown")
    print(f"benchmark parameters: size={size} generator={generator}")
    benchmarks = metadata.get("benchmarks")
    if isinstance(benchmarks, list) and benchmarks:
        parts = []
        source_names = {source.name for source in sources}
        for item in benchmarks:
            if not isinstance(item, dict):
                continue
            name = str(item.get("file", ""))
            if name not in source_names:
                continue
            stem = Path(name).stem
            n = item.get("n", "?")
            parts.append(f"{stem}: n={n}")
        if parts:
            print("benchmark sizes: " + "; ".join(parts))


def run_command(
    command: list[str],
    cwd: Path | None = None,
    timeout: float | None = None,
) -> tuple[int, str, str, float, bool]:
    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        return result.returncode, result.stdout, result.stderr, elapsed, False
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return 124, stdout, stderr, elapsed, True


TIME_DETAIL_RE = re.compile(r"^\s*(setup|lex|parse|register|execute|total):\s+([0-9.]+)\s+s\s*$")


def parse_time_detail(stdout: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in stdout.splitlines():
        match = TIME_DETAIL_RE.match(line)
        if match:
            values[f"ofort_{match.group(1)}_seconds"] = float(match.group(2))
    return values


def make_base_row(source: Path, task: Task) -> dict[str, object]:
    return {
        "benchmark": source.name,
        "source": str(source),
        "task": task.name,
        "kind": task.kind,
        "tool": task.executable,
        "options": " ".join(task.options),
        "version": task.version,
        "command": "",
        "compile_seconds": None,
        "run_seconds": None,
        "total_seconds": None,
        "returncode": None,
        "timed_out": False,
        "success": False,
        "stdout": "",
        "stderr": "",
    }


def run_ofort(source: Path, task: Task, timeout: float | None) -> dict[str, object]:
    row = make_base_row(source, task)
    command = [task.executable, *task.options, "--time-detail", str(source)]
    rc, stdout, stderr, elapsed, timed_out = run_command(command, cwd=ROOT, timeout=timeout)
    row.update(
        {
            "command": subprocess.list2cmdline(command),
            "run_seconds": elapsed,
            "total_seconds": elapsed,
            "returncode": rc,
            "timed_out": timed_out,
            "success": rc == 0 and not timed_out,
            "stdout": stdout,
            "stderr": stderr,
        }
    )
    row.update(parse_time_detail(stdout))
    return row


def run_compiler(source: Path, task: Task, timeout: float | None) -> dict[str, object]:
    row = make_base_row(source, task)
    with tempfile.TemporaryDirectory(prefix=f"{task.name}_") as tmp:
        tmpdir = Path(tmp)
        exe = tmpdir / (source.stem + ".exe")
        if task.executable == "ifx":
            compile_command = [
                task.executable,
                *task.options,
                str(source),
                f"/Fe:{exe}",
            ]
        else:
            compile_command = [
                task.executable,
                *task.options,
                str(source),
                "-o",
                str(exe),
            ]
        rc, stdout, stderr, compile_seconds, timed_out = run_command(
            compile_command, cwd=tmpdir, timeout=timeout
        )
        command_text = subprocess.list2cmdline(compile_command)
        run_seconds = None
        run_stdout = ""
        run_stderr = ""
        run_rc = rc
        run_timed_out = False
        if rc == 0 and not timed_out:
            run_command_line = [str(exe)]
            run_rc, run_stdout, run_stderr, run_seconds, run_timed_out = run_command(
                run_command_line, cwd=tmpdir, timeout=timeout
            )
            command_text += " && " + subprocess.list2cmdline(run_command_line)

    row.update(
        {
            "command": command_text,
            "compile_seconds": compile_seconds,
            "run_seconds": run_seconds,
            "total_seconds": compile_seconds + (run_seconds or 0.0),
            "returncode": run_rc,
            "timed_out": timed_out or run_timed_out,
            "success": run_rc == 0 and not timed_out and not run_timed_out,
            "stdout": stdout + run_stdout,
            "stderr": stderr + run_stderr,
        }
    )
    return row


WINDOWS_STATUS_NAMES = {
    0xC0000005: "access violation",
    0xC00000FD: "stack overflow",
    0xC0000006: "in-page error",
    0xC000013A: "control-c exit",
}


def format_returncode(value: object) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return str(value)
    status = code & 0xFFFFFFFF
    name = WINDOWS_STATUS_NAMES.get(status)
    if name:
        return f"{code} ({name})"
    return str(code)


def print_failure(row: dict[str, object]) -> None:
    print("benchmark failed", file=sys.stderr)
    print(f"  benchmark:  {row.get('benchmark', '')}", file=sys.stderr)
    print(f"  task:       {row.get('task', '')}", file=sys.stderr)
    print(f"  command:    {row.get('command', '')}", file=sys.stderr)
    print(f"  returncode: {format_returncode(row.get('returncode', ''))}", file=sys.stderr)
    print(f"  timed out:  {row.get('timed_out', '')}", file=sys.stderr)
    stderr = str(row.get("stderr") or "").strip()
    stdout = str(row.get("stdout") or "").strip()
    if stderr:
        print("\nstderr:", file=sys.stderr)
        print(stderr, file=sys.stderr)
    elif stdout:
        print("\nstdout:", file=sys.stderr)
        print(stdout, file=sys.stderr)


def tool_available(task: Task) -> bool:
    path = Path(task.executable)
    if path.exists():
        return True
    return shutil.which(task.executable) is not None


def validate_required_tools(tasks: list[Task]) -> int:
    missing = [task for task in tasks if task.enabled and not tool_available(task)]
    if not missing:
        return 0
    printed: set[str] = set()
    for task in missing:
        if task.executable in printed:
            continue
        printed.add(task.executable)
        print(f"error: required executable not found: {task.executable}", file=sys.stderr)
        if Path(task.executable).name.lower().startswith("ofort"):
            print("       build it with `make` or pass --ofort PATH\\to\\ofort.exe", file=sys.stderr)
    return 2


def normalize_version_line(executable: str, line: str) -> str:
    lower_name = Path(executable).name.lower()
    if "gfortran" in lower_name:
        match = re.search(r"\(GCC\)\s+(\S+)\s+(\d{8})", line)
        if match:
            return f"{match.group(1)} {match.group(2)}"
    if "lfortran" in lower_name:
        match = re.search(r"LFortran version:\s*(\S+)", line)
        if match:
            return match.group(1)
    if "ifx" in lower_name:
        match = re.search(r"Version\s+([0-9.]+)\s+Build\s+(\d+)", line, re.IGNORECASE)
        if match:
            return f"{match.group(1)} {match.group(2)}"
    return line


def compiler_name_from_build_info(executable: Path) -> str:
    build_info = executable.with_name("ofort.build")
    if not build_info.exists():
        return ""
    for line in build_info.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "cc":
            compiler = Path(value.strip()).name.lower()
            if compiler.endswith(".exe"):
                compiler = compiler[:-4]
            if "clang" in compiler:
                return "clang"
            if "gcc" in compiler:
                return "gcc"
            return compiler
    return ""


def tool_version(executable: str) -> str:
    path = Path(executable)
    if not path.exists() and shutil.which(executable) is None:
        return "not found"
    if "ofort" in path.name.lower():
        resolved = path if path.exists() else Path(shutil.which(executable) or executable)
        date = time.strftime("%Y%m%d", time.localtime(resolved.stat().st_mtime))
        compiler = compiler_name_from_build_info(resolved)
        return f"{compiler} {date}" if compiler else date
    version_option = "/QV" if "ifx" in Path(executable).name.lower() else "--version"
    rc, stdout, stderr, _, timed_out = run_command([executable, version_option], timeout=5.0)
    if rc != 0 or timed_out:
        return "unknown"
    for line in (stdout + stderr).splitlines():
        line = line.strip()
        if line:
            return normalize_version_line(executable, line)
    return "unknown"


def make_task(
    name: str,
    enabled: bool,
    kind: str,
    executable: str,
    options: list[str],
) -> Task:
    return Task(name, enabled, kind, executable, options, tool_version(executable))


def build_tasks(args: argparse.Namespace) -> list[Task]:
    gfortran_exe = args.gfortran or "gfortran"
    ifx_exe = args.ifx or "ifx"
    lfortran_exe = args.lfortran or "lfortran"
    restricted_ofort_set = args.ofort_only or args.ofort_fast
    use_gfortran = RUN_GFORTRAN and not args.no_gfortran and (
        not restricted_ofort_set or args.gfortran is not None
    )
    use_ifx = RUN_IFX and not args.no_ifx and (
        not restricted_ofort_set or args.ifx is not None
    )
    use_lfortran = RUN_LFORTRAN and not args.no_lfortran and (
        not restricted_ofort_set or args.lfortran is not None
    )
    return [
        make_task(
            "ofort",
            RUN_OFORT and not args.no_ofort and not args.ofort_fast,
            "interpreter",
            str(args.ofort),
            [],
        ),
        make_task(
            "ofort" if args.ofort_fast else "ofort_fast",
            RUN_OFORT_FAST and not args.no_ofort_fast,
            "interpreter",
            str(args.ofort),
            ["--fast"],
        ),
        make_task(
            "gfortran",
            use_gfortran,
            "compiler",
            gfortran_exe,
            list(args.gfortran_options),
        ),
        make_task("ifx", use_ifx, "compiler", ifx_exe, list(args.ifx_options)),
        make_task(
            "lfortran",
            use_lfortran,
            "compiler",
            lfortran_exe,
            list(args.lfortran_options),
        ),
    ]


def geomean(values: "pd.Series") -> float:
    if values.empty or values.isna().any() or (values <= 0.0).any():
        return math.nan
    return math.exp(sum(math.log(float(value)) for value in values) / len(values))


def add_mean_rows(df: "pd.DataFrame") -> "pd.DataFrame":
    rows = [df]
    for label, func in (("mean", "mean"), ("geomean", geomean)):
        aggregate_rows: list[dict[str, object]] = []
        for task, group in df.groupby("task", sort=False):
            complete = bool(group["success"].all()) and not group["run_seconds"].isna().any()
            aggregate_rows.append(
                {
                    "benchmark": label,
                    "task": task,
                    "success": int(group["success"].sum()),
                    "run_seconds": getattr(group["run_seconds"], func)()
                    if complete and isinstance(func, str)
                    else func(group["run_seconds"])
                    if complete
                    else math.nan,
                    "total_seconds": getattr(group["total_seconds"], func)()
                    if complete and isinstance(func, str)
                    else func(group["total_seconds"])
                    if complete
                    else math.nan,
                }
            )
        rows.append(pd.DataFrame(aggregate_rows))
    return pd.concat(rows, ignore_index=True, sort=False)


def make_totals_by_task(df: "pd.DataFrame") -> "pd.DataFrame":
    time_cols = ["compile_seconds", "run_seconds", "total_seconds"]
    totals_source = df.copy()
    is_interpreter = totals_source["kind"] == "interpreter"
    totals_source["compile_seconds"] = pd.to_numeric(
        totals_source["compile_seconds"], errors="coerce"
    )
    totals_source.loc[is_interpreter, "compile_seconds"] = totals_source.loc[
        is_interpreter, "compile_seconds"
    ].fillna(0.0)
    totals = totals_source.groupby("task", sort=False)[time_cols].sum(min_count=1).reset_index()
    success_counts = totals_source.groupby("task", sort=False)["success"].sum().reset_index()
    totals.insert(1, "#success", success_counts["success"].astype(int))
    counts = totals_source.groupby("task", sort=False).size().reset_index(name="count")
    for col in time_cols:
        short_name = col.removesuffix("_seconds")
        totals[f"avg_{short_name}_seconds"] = totals[col] / counts["count"]
    metadata = totals_source.groupby("task", sort=False)[["version", "options"]].first().reset_index()
    totals["version"] = metadata["version"]
    totals["options"] = metadata["options"]
    overall = {"task": "overall"}
    overall["#success"] = int(totals["#success"].sum())
    for col in time_cols:
        overall[col] = totals[col].sum(min_count=1)
    total_count = int(counts["count"].sum())
    for col in time_cols:
        short_name = col.removesuffix("_seconds")
        overall[f"avg_{short_name}_seconds"] = overall[col] / total_count if total_count else math.nan
    overall["version"] = ""
    overall["options"] = ""
    return pd.concat([totals, pd.DataFrame([overall])], ignore_index=True)


def make_totals_by_program(df: "pd.DataFrame") -> "pd.DataFrame":
    table_source = df.copy()
    is_interpreter = table_source["kind"] == "interpreter"
    table_source["compile_seconds"] = pd.to_numeric(
        table_source["compile_seconds"], errors="coerce"
    )
    table_source.loc[is_interpreter, "compile_seconds"] = table_source.loc[
        is_interpreter, "compile_seconds"
    ].fillna(0.0)
    table_source["program"] = table_source["benchmark"].map(
        lambda value: Path(value).stem if str(value).lower().endswith(".f90") else value
    )

    tasks = list(dict.fromkeys(table_source["task"]))
    result = pd.DataFrame({"program": list(dict.fromkeys(table_source["program"]))})
    for time_name, column in (
        ("total", "total_seconds"),
        ("run", "run_seconds"),
        ("compile", "compile_seconds"),
    ):
        pivot = table_source.pivot(index="program", columns="task", values=column)
        for task in tasks:
            task_kind = table_source.loc[table_source["task"] == task, "kind"].iloc[0]
            if time_name == "compile" and task_kind == "interpreter":
                continue
            result[f"{task}_{time_name}"] = result["program"].map(pivot[task])
    numeric_cols = [col for col in result.columns if col != "program"]
    aggregate_rows: list[dict[str, object]] = []
    for label, func in (
        ("*MEAN*", lambda series: series.mean(skipna=True)),
        ("*GEOMEAN*", geomean),
        ("*MEDIAN*", lambda series: series.median(skipna=True)),
        ("*MIN*", lambda series: series.min(skipna=True)),
        ("*MAX*", lambda series: series.max(skipna=True)),
    ):
        row: dict[str, object] = {"program": label}
        for col in numeric_cols:
            row[col] = func(pd.to_numeric(result[col], errors="coerce"))
        aggregate_rows.append(row)
    if aggregate_rows:
        result = pd.concat([result, pd.DataFrame(aggregate_rows)], ignore_index=True)
    return result


def format_seconds(value: object) -> str:
    if pd.isna(value):
        return "nan"
    return f"{float(value):.4f}"


def print_summary(df: "pd.DataFrame", run_only: bool = False) -> None:
    if df.empty:
        print("no benchmark rows")
        return
    cols = ["benchmark", "task", "success", "run_seconds", "total_seconds"]
    summary = add_mean_rows(df)[cols].copy()
    if run_only:
        summary = summary.drop(columns=["total_seconds"])
    summary["benchmark"] = summary["benchmark"].map(
        lambda value: Path(value).stem if str(value).lower().endswith(".f90") else value
    )
    summary["success"] = summary["success"].map(int)
    for col in ("run_seconds", "total_seconds"):
        if col not in summary.columns:
            continue
        summary[col] = summary[col].map(format_seconds)
    summary = summary.rename(
        columns={
            "success": "#success",
            "run_seconds": "run",
            "total_seconds": "total",
        }
    )
    print("times in seconds")
    print(summary.to_string(index=False))


def print_totals_by_task(df: "pd.DataFrame", run_only: bool = False) -> None:
    totals = make_totals_by_task(df)
    time_cols = [
        "compile_seconds",
        "run_seconds",
        "total_seconds",
        "avg_compile_seconds",
        "avg_run_seconds",
        "avg_total_seconds",
    ]
    if run_only:
        totals = totals.drop(
            columns=[
                "compile_seconds",
                "total_seconds",
                "avg_compile_seconds",
                "avg_total_seconds",
            ]
        )
        time_cols = [col for col in time_cols if col in totals.columns]
    for col in time_cols:
        totals[col] = totals[col].map(format_seconds)
    totals = totals.rename(
        columns={
            "compile_seconds": "compile",
            "run_seconds": "run",
            "total_seconds": "total",
            "avg_compile_seconds": "avg_compile",
            "avg_run_seconds": "avg_run",
            "avg_total_seconds": "avg_total",
        }
    )
    print()
    print("time sums by task")
    print(totals.to_string(index=False))


def add_run_ratio_columns(totals: "pd.DataFrame", df: "pd.DataFrame") -> "pd.DataFrame":
    tasks = list(dict.fromkeys(df["task"]))
    kinds = {
        task: df.loc[df["task"] == task, "kind"].iloc[0]
        for task in tasks
    }
    ofort_task = "ofort" if "ofort" in tasks else None
    if not ofort_task:
        return totals
    ofort_run = f"{ofort_task}_run"
    if ofort_run not in totals.columns:
        return totals
    ratio_cols: dict[str, object] = {}
    for task in tasks:
        if task == ofort_task or kinds.get(task) != "compiler":
            continue
        compiler_run = f"{task}_run"
        if compiler_run not in totals.columns:
            continue
        ratio_cols[f"ratio_ofort_{task}"] = totals[ofort_run] / totals[compiler_run]
    if not ratio_cols:
        return totals

    result = totals.copy()
    insert_at = 1
    for i, col in enumerate(result.columns):
        if col.endswith("_run"):
            insert_at = i + 1
    for name, values in ratio_cols.items():
        result.insert(insert_at, name, values)
        insert_at += 1
    return result


def print_totals_by_program(
    df: "pd.DataFrame",
    run_only: bool = False,
    include_ratios: bool = True,
) -> None:
    totals = make_totals_by_program(df)
    if run_only:
        drop_cols = [
            col
            for col in totals.columns
            if col.endswith("_compile") or col.endswith("_total")
        ]
        totals = totals.drop(columns=drop_cols)
    if include_ratios:
        totals = add_run_ratio_columns(totals, df)
    for col in totals.columns:
        if col != "program":
            totals[col] = totals[col].map(format_seconds)
    display = totals.copy()
    display_columns: list[tuple[str, str]] = []
    for col in display.columns:
        if col == "program":
            display_columns.append(("program", ""))
        elif col.startswith("ratio_ofort_"):
            compiler = col.removeprefix("ratio_ofort_")
            display_columns.append(("run ratio", f"ofort/{compiler}"))
        else:
            task, sep, metric = col.rpartition("_")
            display_columns.append((task if sep else col, metric if sep else ""))
    display.columns = pd.MultiIndex.from_tuples(display_columns)
    print()
    print("time sums by program")
    print(display.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "patterns",
        nargs="*",
        default=[DEFAULT_BENCHMARK_GLOB],
        help=f"benchmark files or globs (default: {DEFAULT_BENCHMARK_GLOB})",
    )
    parser.add_argument("--ofort", type=Path, default=DEFAULT_OFORT)
    parser.add_argument(
        "--gfortran",
        nargs="?",
        const="gfortran",
        help="include gfortran, optionally with an executable path",
    )
    parser.add_argument(
        "--ifx",
        nargs="?",
        const="ifx",
        help="include ifx, optionally with an executable path",
    )
    parser.add_argument(
        "--lfortran",
        nargs="?",
        const="lfortran",
        help="include lfortran, optionally with an executable path",
    )
    parser.add_argument("--gfortran-options", nargs="*", default=GFORTRAN_OPTIONS)
    parser.add_argument("--ifx-options", nargs="*", default=IFX_OPTIONS)
    parser.add_argument("--lfortran-options", nargs="*", default=LFORTRAN_OPTIONS)
    parser.add_argument("--no-ofort", action="store_true")
    parser.add_argument("--no-ofort-fast", action="store_true")
    parser.add_argument("--no-gfortran", action="store_true")
    parser.add_argument("--no-ifx", action="store_true")
    parser.add_argument("--no-lfortran", action="store_true")
    parser.add_argument(
        "--ofort-only",
        action="store_true",
        help="run only ofort and ofort --fast",
    )
    parser.add_argument(
        "--ofort-fast",
        action="store_true",
        help="run ofort --fast, plus explicitly requested compilers",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="timeout in seconds for each compile or run step; use 0 for no timeout",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--noratio",
        action="store_true",
        help="do not show ofort/compiler run-time ratios in the per-program table",
    )
    parser.add_argument(
        "--run-only",
        action="store_true",
        help="show only run times, omitting compile and total times",
    )
    parser.add_argument(
        "--no-list",
        action="store_true",
        help="do not print each benchmark/task name before it runs",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first failed benchmark row and print its error",
    )
    parser.add_argument("--limit", type=int, metavar="N", help="run at most N benchmark files")
    args = parser.parse_args(argv)

    if args.timeout < 0:
        print("--timeout must be non-negative", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2
    timeout = None if args.timeout == 0 else args.timeout

    sources = expand_patterns(args.patterns)
    if not sources:
        print("no benchmarks matched", file=sys.stderr)
        return 2
    if args.limit is not None:
        sources = sources[: args.limit]

    tasks = [task for task in build_tasks(args) if task.enabled]
    missing_rc = validate_required_tools(tasks)
    if missing_rc:
        return missing_rc
    run_only_output = args.run_only or (
        args.ofort_only and all(task.kind == "interpreter" for task in tasks)
    )
    suppress_summary = args.ofort_only and all(task.kind == "interpreter" for task in tasks)
    rows: list[dict[str, object]] = []
    if not args.quiet:
        print_benchmark_parameters(sources)
    if args.ofort_fast and not args.quiet:
        print("note: ofort refers to ofort --fast")
    for task in tasks:
        if not tool_available(task):
            for source in sources:
                row = make_base_row(source, task)
                row.update(
                    {
                        "command": task.executable,
                        "stderr": f"tool not found: {task.executable}",
                        "returncode": 127,
                    }
                )
                rows.append(row)
                if args.fail_fast:
                    print_failure(row)
                    return 1
            continue
        for source in sources:
            if not args.quiet and not args.no_list:
                print(f"{task.name}: {source.name}", flush=True)
            if task.kind == "interpreter":
                row = run_ofort(source, task, timeout)
            else:
                row = run_compiler(source, task, timeout)
            rows.append(row)
            if args.fail_fast and not bool(row["success"]):
                print_failure(row)
                return 1

    require_pandas()
    df = pd.DataFrame(rows)
    if not args.no_csv:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        if not args.quiet:
            print(f"\nwrote {args.output}")
    if not args.quiet:
        if not suppress_summary and not args.run_only:
            print()
            print_summary(df, run_only=run_only_output)
        print_totals_by_task(df, run_only=run_only_output)
        print_totals_by_program(
            df,
            run_only=run_only_output,
            include_ratios=not args.noratio,
        )
    return 0 if bool(df["success"].all()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
