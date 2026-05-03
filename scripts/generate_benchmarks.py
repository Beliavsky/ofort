#!/usr/bin/env python3
"""Generate ofort benchmark Fortran programs with a configurable problem size."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "benchmarks"
DEFAULT_SIZE = 1_000_000
METADATA_NAME = "benchmark_parameters.json"


@dataclass(frozen=True)
class BenchmarkTemplate:
    name: str
    factor_num: int
    factor_den: int
    source: str

    def problem_size(self, base_size: int) -> int:
        return max(1, base_size * self.factor_num // self.factor_den)


TEMPLATES = [
    BenchmarkTemplate(
        "xbench_array_axpy.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n), y(n)
call random_number(x)
y = 2.5_dp*x + 1.0_dp
print*, n, sum(y)/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_array_expr_assign.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n), y(n)
call random_number(x)
y = x*x + 2.0_dp*x + 1.0_dp
print*, n, sum(y)/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_array_loop_assign.f90",
        1,
        5,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n), y(n), a, b
integer :: i
a = 2.5_dp
b = 1.0_dp
call random_number(x)
do i = 1, n
   y(i) = a*x(i) + b
end do
print*, n, sum(y)/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_array_minmax.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, minval(x), maxval(x)
end
""",
    ),
    BenchmarkTemplate(
        "xbench_array_moments.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, sum(x)/n, sum(x**2)/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_array_product_reduction.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, product(1.0_dp + x/n)
end
""",
    ),
    BenchmarkTemplate(
        "xbench_scalar_affine_loop.f90",
        5,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y, a, b
integer :: i
x = 0.25_dp
y = 1.0_dp
a = 1.000001_dp
b = 0.125_dp
do i = 1, n
   y = a*y + b*x
end do
print*, n, y
end
""",
    ),
    BenchmarkTemplate(
        "xbench_scalar_dot_loop.f90",
        2,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y, dot
integer :: i
dot = 0.0_dp
do i = 1, n
   call random_number(x)
   call random_number(y)
   dot = dot + x*y
end do
print*, n, dot/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_scalar_random_sum_loop.f90",
        2,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, xsum
integer :: i
xsum = 0.0_dp
do i = 1, n
   call random_number(x)
   xsum = xsum + x
end do
print*, n, xsum/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_scalar_poly_loop.f90",
        5,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, s
integer :: i
x = 0.25_dp
s = 0.0_dp
do i = 1, n
   x = 0.999999_dp*x + 0.000001_dp
   s = s + x*x + 2.0_dp*x + 1.0_dp
end do
print*, n, s/n
end
""",
    ),
    BenchmarkTemplate(
        "xbench_scalar_recurrence.f90",
        5,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y
integer :: i
x = 0.125_dp
y = 1.0_dp
do i = 1, n
   y = 0.999999_dp*y + x
end do
print*, n, y
end
""",
    ),
    BenchmarkTemplate(
        "xbench_subroutine_loop.f90",
        1,
        1,
        """integer, parameter :: n = {n}
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x
integer :: i
x = 1.0_dp
do i = 1, n
   call update(x)
end do
print*, n, x
contains
subroutine update(y)
  real(kind=dp), intent(inout) :: y
  y = 0.999999_dp*y + 0.125_dp
end subroutine update
end
""",
    ),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--size",
        type=int,
        default=DEFAULT_SIZE,
        help=f"base problem size used to derive each benchmark's n (default: {DEFAULT_SIZE})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print generated file names and derived n values",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.size < 1:
        raise SystemExit("--size must be at least 1")

    args.out.mkdir(parents=True, exist_ok=True)
    metadata = {
        "generator": "scripts/generate_benchmarks.py",
        "size": args.size,
        "benchmarks": [],
    }
    for template in TEMPLATES:
        n = template.problem_size(args.size)
        path = args.out / template.name
        path.write_text(template.source.format(n=n), encoding="utf-8", newline="\n")
        metadata["benchmarks"].append(
            {
                "file": template.name,
                "n": n,
                "factor": f"{template.factor_num}/{template.factor_den}",
            }
        )
        if args.list:
            print(f"{path} n={n}")
    (args.out / METADATA_NAME).write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if not args.list:
        print(f"wrote {len(TEMPLATES)} benchmarks to {args.out} with base size {args.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
