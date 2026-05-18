#!/usr/bin/env python3
"""Compare gfortran and ofort output for one or more Fortran source files.

The script compiles and runs the source with gfortran, squeezes the output
whitespace, then runs ofort on the same source and squeezes that output.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"
_WHITESPACE_RE = re.compile(r"\s+")
_SIGNED_ZERO_RE = re.compile(r"(?<![\w.])-0(?:\.0+)?(?=$|\s)")
_GFORTRAN_LINE_RE = re.compile(r"\bAt line\s+(\d+)\s+of file\b", re.IGNORECASE)
_OFORT_LINE_RE = re.compile(r"^(?:[A-Za-z]:)?[^\n]*?:(\d+):", re.MULTILINE)


def squeeze_text(text: str) -> str:
    lines = [
        _SIGNED_ZERO_RE.sub(lambda m: m.group(0)[1:], _WHITESPACE_RE.sub(" ", line.strip()))
        for line in text.splitlines()
    ]
    return "\n".join(lines)


def print_block(title: str, result: subprocess.CompletedProcess[str]) -> None:
    print(title)
    out = squeeze_text(result.stdout)
    err = squeeze_text(result.stderr)
    if out:
        print(out)
    if err:
        print("stderr:")
        print(err)
    print(f"exit code: {result.returncode}")


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def failure_line(result: subprocess.CompletedProcess[str]) -> int | None:
    text = result.stderr or ""
    match = _GFORTRAN_LINE_RE.search(text)
    if match:
        return int(match.group(1))
    match = _OFORT_LINE_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def results_match(gfortran_result: subprocess.CompletedProcess[str],
                  ofort_result: subprocess.CompletedProcess[str],
                  same_failure_ok: bool) -> bool:
    gfortran_out = squeeze_text(gfortran_result.stdout)
    ofort_out = squeeze_text(ofort_result.stdout)
    if gfortran_result.returncode == ofort_result.returncode and gfortran_out == ofort_out:
        return True
    if same_failure_ok and gfortran_result.returncode != 0 and ofort_result.returncode != 0:
        if gfortran_out == ofort_out:
            return True
        gfortran_line = failure_line(gfortran_result)
        ofort_line = failure_line(ofort_result)
        return gfortran_line is not None and gfortran_line == ofort_line
    return False


def resolve_source(name: str, base_dir: Path | None = None) -> Path | None:
    source = Path(name)
    if not source.is_absolute() and base_dir is not None:
        source = base_dir / source
    if source.exists():
        return source
    if source.suffix == "":
        with_f90 = source.with_suffix(".f90")
        if with_f90.exists():
            return with_f90
    return None


def read_manifest(arg: str, skip: int, skip_lines: int) -> tuple[list[Path], list[str]]:
    manifest = Path(arg[1:])
    if not manifest.exists():
        return [], [f"manifest not found: {arg[1:]}"]

    sources: list[Path] = []
    errors: list[str] = []
    base_dir = manifest.parent
    seen_entries = 0
    for line_no, raw in enumerate(manifest.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if line_no <= skip_lines:
            continue
        item = raw.strip()
        if not item or item.startswith("#") or item.startswith("!"):
            continue
        if seen_entries < skip:
            seen_entries += 1
            continue
        seen_entries += 1
        source = resolve_source(item, base_dir)
        if source is None:
            errors.append(f"{manifest}:{line_no}: source not found: {item}")
        else:
            sources.append(source)
    return sources, errors


def source_args(arg: str, skip: int, skip_lines: int) -> tuple[list[Path], list[str]]:
    if arg.startswith("@") and len(arg) > 1:
        return read_manifest(arg, skip, skip_lines)
    if skip:
        return [], ["--skip is only valid with @manifest input"]
    if skip_lines:
        return [], ["--skip-lines is only valid with @manifest input"]
    source = resolve_source(arg)
    if source is None:
        return [], [f"source not found: {arg}"]
    return [source], []


def compare_source(source: Path, args: argparse.Namespace, show_header: bool) -> int:
    if show_header:
        print(f"==> {source}")

    with tempfile.TemporaryDirectory(prefix="og_", dir=None) as td:
        tmpdir = Path(td)
        exe = tmpdir / ("a.exe" if os.name == "nt" else "a.out")
        gfortran_cmd = [args.gfortran]
        ofort_cmd = [args.ofort]
        if args.no_warn:
            gfortran_cmd.append("-w")
            ofort_cmd.append("-w")

        compile_result = run_command([*gfortran_cmd, str(source), "-o", str(exe)], ROOT)
        if compile_result.returncode != 0:
            print_block("gfortran compile", compile_result)
            return compile_result.returncode

        gfortran_result = run_command([str(exe)], ROOT)
        ofort_result = run_command([*ofort_cmd, str(source)], ROOT)

        if args.diff:
            gfortran_out = squeeze_text(gfortran_result.stdout)
            ofort_out = squeeze_text(ofort_result.stdout)
            if results_match(gfortran_result, ofort_result, args.same_failure_ok):
                print("outputs match")
            else:
                print(f"gfortran exit code: {gfortran_result.returncode}")
                print(f"ofort exit code: {ofort_result.returncode}")
                diff = difflib.unified_diff(
                    gfortran_out.splitlines(),
                    ofort_out.splitlines(),
                    fromfile="gfortran",
                    tofile="ofort",
                    lineterm="",
                )
                print("\n".join(diff))
                if gfortran_result.stderr or ofort_result.stderr:
                    print()
                    if gfortran_result.stderr:
                        print("gfortran stderr:")
                        print(squeeze_text(gfortran_result.stderr))
                    if ofort_result.stderr:
                        print("ofort stderr:")
                        print(squeeze_text(ofort_result.stderr))
        else:
            print_block("gfortran", gfortran_result)
            print()
            print_block("ofort", ofort_result)

        if args.keep_exe:
            kept = ROOT / f"{source.stem}_{exe.name}"
            kept.write_bytes(exe.read_bytes())
            print()
            print(f"kept executable: {kept}")

        if args.diff:
            return 0 if results_match(gfortran_result, ofort_result, args.same_failure_ok) else 1
        if results_match(gfortran_result, ofort_result, args.same_failure_ok):
            return 0
        return 0 if gfortran_result.returncode == 0 and ofort_result.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile/run with gfortran and run with ofort, normalizing whitespace."
    )
    parser.add_argument("source", help="Fortran source file, or @manifest with one source per line")
    parser.add_argument(
        "--ofort",
        default=str(OFORT),
        help="Path to ofort executable",
    )
    parser.add_argument(
        "--gfortran",
        default="gfortran",
        help="gfortran command",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Compare squeezed gfortran and ofort stdout and print a unified diff if they differ.",
    )
    parser.add_argument(
        "--keep-exe",
        action="store_true",
        help="Keep the temporary gfortran executable",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="With @manifest input, skip the first n non-comment, nonblank entries.",
    )
    parser.add_argument(
        "--skip-lines",
        type=int,
        default=0,
        help="With @manifest input, skip the first n raw manifest lines before comment filtering.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most n source files.",
    )
    parser.add_argument(
        "--max-fail",
        type=int,
        default=None,
        help="Stop after n failed comparisons or runs.",
    )
    parser.add_argument(
        "--no-warn",
        action="store_true",
        help="Pass -w to both gfortran and ofort.",
    )
    parser.add_argument(
        "--same-failure-ok",
        action="store_true",
        help="Treat matching stdout with nonzero exits from both compilers as success.",
    )
    args = parser.parse_args(argv)

    if args.skip < 0:
        print("--skip must be non-negative", file=sys.stderr)
        return 2
    if args.skip_lines < 0:
        print("--skip-lines must be non-negative", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2
    if args.max_fail is not None and args.max_fail < 1:
        print("--max-fail must be at least 1", file=sys.stderr)
        return 2

    sources, errors = source_args(args.source, args.skip, args.skip_lines)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    if args.limit is not None:
        sources = sources[:args.limit]

    failures = 0
    for index, source in enumerate(sources):
        if index > 0:
            print()
        rc = compare_source(source, args, show_header=len(sources) > 1)
        if rc != 0:
            failures += 1
            if args.max_fail is not None and failures >= args.max_fail:
                remaining = len(sources) - index - 1
                if remaining > 0:
                    print(
                        f"stopped after {failures} failures; {remaining} sources not processed",
                        file=sys.stderr,
                    )
                break
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
