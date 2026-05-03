#!/usr/bin/env python3
"""Run ofort over one or more file globs."""

from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFORT = ROOT / ("ofort.exe" if sys.platform.startswith("win") else "ofort")


def expand_patterns(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            path = Path(pattern)
            if path.exists():
                matches = [pattern]
        for match in sorted(matches):
            path = Path(match)
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(path)

    return files


def count_lines(path: Path) -> int:
    count = 0
    with path.open("rb") as f:
        for count, _ in enumerate(f, start=1):
            pass
    return count


def print_header(source: Path, line_count: int, first: bool) -> None:
    if not first:
        print()
    print(f"==> {source} ({line_count} lines)", flush=True)


def passes_filter(filter_cmd: str, source: Path, timeout: float | None) -> bool:
    command = f'{filter_cmd} "{source.resolve()}"'
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=tmpdir,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False
    return result.returncode == 0


def run_one(
    ofort: Path,
    source: Path,
    line_count: int,
    check: bool,
    first: bool,
    timeout: float | None,
    quiet: bool,
) -> tuple[int, bool]:
    cmd = [str(ofort)]
    if check:
        cmd.append("--check")
    cmd.append(str(source))

    if not quiet:
        print_header(source, line_count, first)
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if quiet:
            print_header(source, line_count, first)
        if exc.stdout:
            print(exc.stdout, end="")
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        print(f"timed out after {timeout:g} seconds", file=sys.stderr)
        return 1, True
    if quiet and result.returncode == 0:
        return 0, False
    if quiet:
        print_header(source, line_count, first)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode, quiet and result.returncode != 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run ofort on every file matched by one or more globs."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="pass --check to ofort instead of running each program",
    )
    parser.add_argument(
        "--ofort",
        default=str(DEFAULT_OFORT),
        help=f"path to ofort executable (default: {DEFAULT_OFORT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="run at most N matched files",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="per-file timeout in seconds; use 0 for no timeout (default: 30)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        metavar="N",
        help="skip files longer than N lines",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="only print output for files that fail or time out",
    )
    parser.add_argument(
        "--filter",
        metavar="CMD",
        help="skip files for which CMD followed by the source file returns nonzero",
    )
    parser.add_argument("patterns", nargs="+", help="file paths or glob patterns")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2
    if args.timeout < 0:
        print("--timeout must be non-negative", file=sys.stderr)
        return 2
    if args.max_lines is not None and args.max_lines < 0:
        print("--max-lines must be non-negative", file=sys.stderr)
        return 2

    ofort = Path(args.ofort)
    if not ofort.exists():
        print(f"ofort executable not found: {ofort}", file=sys.stderr)
        return 2

    files = expand_patterns(args.patterns)
    if not files:
        print("no files matched", file=sys.stderr)
        return 2
    if args.limit is not None:
        files = files[: args.limit]

    start = time.perf_counter()
    failures = 0
    passed = 0
    skipped = 0
    timeout = None if args.timeout == 0 else args.timeout
    ran_any = False
    printed_any = False
    for i, source in enumerate(files):
        line_count = count_lines(source)
        if args.max_lines is not None and line_count > args.max_lines:
            skipped += 1
            continue
        if args.filter and not passes_filter(args.filter, source, timeout):
            skipped += 1
            continue

        first_output = not printed_any if args.quiet else not ran_any
        rc, printed = run_one(
            ofort,
            source,
            line_count,
            args.check,
            first_output,
            timeout,
            args.quiet,
        )
        ran_any = True
        if printed:
            printed_any = True
        if rc != 0:
            failures += 1
        else:
            passed += 1

    elapsed = time.perf_counter() - start
    if failures:
        suffix = f", {skipped} skipped" if skipped else ""
        print(f"{failures} of {len(files)} failed{suffix} in {elapsed:.2f}s", file=sys.stderr)
        return 1

    if args.quiet:
        return 0

    if skipped:
        print(f"{passed} passed, {skipped} skipped in {elapsed:.2f}s")
    else:
        print(f"{passed} passed in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
