#!/usr/bin/env python3
"""Generate and run the benchmark suite for multiple base problem sizes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import bench_ofort


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEFAULT_BENCHMARKS_DIR = ROOT / "benchmarks"
DEFAULT_RESULTS_DIR = ROOT / "benchmarks" / "size_results"


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Options not recognized by this script are passed to bench_ofort.py. "
            "Example: python scripts\\bench_sizes.py 1000000 5000000 --ofort-fast --gfortran --run-only"
        ),
    )
    parser.add_argument("sizes", nargs="+", type=int, help="base benchmark sizes to run")
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=DEFAULT_BENCHMARKS_DIR,
        help=f"directory where generated .f90 files are written (default: {DEFAULT_BENCHMARKS_DIR})",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help=f"directory for per-size CSV results (default: {DEFAULT_RESULTS_DIR})",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continue to later sizes if a benchmark run fails",
    )
    args, bench_args = parser.parse_known_args(argv)
    return args, bench_args


def run_command(command: list[str], cwd: Path) -> int:
    print()
    print(subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=cwd).returncode


def aggregate_rows_for_size(size: int, csv_path: Path, include_ratios: bool):
    pd = bench_ofort.require_pandas()
    df = pd.read_csv(csv_path)
    totals = bench_ofort.make_totals_by_program(df)
    drop_cols = [
        col
        for col in totals.columns
        if col.endswith("_compile") or col.endswith("_total")
    ]
    totals = totals.drop(columns=drop_cols)
    if include_ratios:
        totals = bench_ofort.add_run_ratio_columns(totals, df)
    totals = totals[totals["program"].isin(["*MEAN*", "*GEOMEAN*", "*MEDIAN*", "*MIN*", "*MAX*"])]
    for col in totals.columns:
        if col != "program":
            totals[col] = totals[col].map(bench_ofort.format_seconds)

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
    return size, display


def print_aggregate_rows(size: int, display) -> None:
    print()
    print(f"aggregate run rows for size {size}")
    print(display.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    args, bench_args = parse_args(argv)
    if any(size < 1 for size in args.sizes):
        print("all sizes must be positive", file=sys.stderr)
        return 2

    args.results_dir.mkdir(parents=True, exist_ok=True)
    generator = SCRIPTS / "generate_benchmarks.py"
    runner = SCRIPTS / "bench_ofort.py"
    overall_rc = 0
    include_ratios = "--noratio" not in bench_args
    aggregate_tables = []

    for size in args.sizes:
        print()
        print(f"== size {size} ==", flush=True)
        rc = run_command(
            [
                sys.executable,
                str(generator),
                "--size",
                str(size),
                "--out",
                str(args.benchmarks_dir),
            ],
            cwd=ROOT,
        )
        if rc != 0:
            overall_rc = rc
            if not args.keep_going:
                return rc
            continue

        output = args.results_dir / f"benchmark_results_size_{size}.csv"
        rc = run_command(
            [
                sys.executable,
                str(runner),
                "--output",
                str(output),
                *bench_args,
            ],
            cwd=ROOT,
        )
        if rc != 0:
            overall_rc = rc
            if not args.keep_going:
                return rc
        elif output.exists():
            aggregate_tables.append(
                aggregate_rows_for_size(size, output, include_ratios=include_ratios)
            )

    if aggregate_tables:
        print()
        print("aggregate run rows by problem size")
        for size, display in aggregate_tables:
            print_aggregate_rows(size, display)

    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
