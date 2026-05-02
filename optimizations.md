# `--fast` Optimizations

`ofort` is primarily a tree-walking interpreter. By default it favors simple
execution paths and broad language behavior over speed. The `--fast` option
enables selected fast paths inside the interpreter for common numeric and array
patterns.

`--fast` does not turn `ofort` into a native-code compiler. It does not emit C,
LLVM, object files, or executables. Programs still run inside the interpreter.

## Command-Line Use

Enable fast mode:

```powershell
.\ofort.exe --fast x.f90
```

Disable specialized pattern/program fast paths while keeping general fast mode:

```powershell
.\ofort.exe --fast --no-specialize x.f90
```

Inspect timing:

```powershell
.\ofort.exe --fast --time x.f90
.\ofort.exe --fast --time-detail x.f90
.\ofort.exe --fast --time-detail --profile-lines x.f90
```

`--profile-lines` is useful for finding hot source lines, but it can also
disable or reduce some loop-level fast paths because profiling needs per-line
accounting.

## General Fast Paths

These optimizations are intended to preserve normal interpreter behavior while
reducing overhead for common cases.

### Packed Numeric Arrays

Numeric arrays can use contiguous C buffers for integer or real data instead of
storing every element as a full tagged interpreter value.

This reduces memory traffic and speeds up:

- element access
- whole-array assignment
- scalar assignment to arrays
- `sum` over numeric arrays
- `random_number` on real arrays

### Faster `random_number`

In fast mode, `random_number` uses a lightweight internal generator and writes
directly into packed real arrays when possible. Scalar `random_number(x)` also
uses the fast generator.

This is much faster for benchmark-style loops and large arrays, but the exact
random sequence is not intended to match a Fortran compiler.

### Cached Variable Lookup

Fast expression evaluation caches some variable lookups by AST node and scope.
This avoids repeatedly searching scope tables in tight scalar numeric loops.

### Fast Scalar Numeric Assignment

Simple numeric assignments can bypass the full generic evaluator. The fast path
handles common scalar arithmetic and selected array-element references.

Examples of patterns that may benefit:

```fortran
xsum = xsum + x
y = a*x + b
a(i) = a(i) + c
```

If an expression is outside the supported fast subset, execution falls back to
the regular interpreter path.

### Numeric DO Loop Plans

For simple counted `do` loops, ofort can build a small cached execution plan
for loop bodies containing numeric assignments and nested counted loops. Later
iterations reuse that plan instead of repeatedly dispatching through the full
AST interpreter.

This helps loops such as:

```fortran
do i = 1, n
   xsum = xsum + x
end do
```

The optimization is deliberately conservative. If the body contains unsupported
statements, it falls back to normal interpretation.

### Reusable Local Arrays

Inside procedures, fixed-shape local numeric arrays may reuse cached storage
when the shape is unchanged. This avoids repeated allocation and initialization
overhead in procedure-heavy numeric code.

### Fast Array Intrinsic Cases

Some array intrinsics have direct paths for packed numeric arrays. Examples
include `sum` and array-oriented cases such as `reshape` where direct copying is
possible.

## Specialized Fast Paths

Specialized fast paths recognize narrow benchmark-like patterns and replace
them with direct C implementations. These are enabled by `--fast` by default
and disabled by `--no-specialize`.

Use these results carefully in benchmark comparisons. A specialized path is
less representative of the general interpreter than the ordinary `--fast`
paths.

### Affine Subroutine Loops

Some loops that repeatedly call a simple scalar subroutine can be collapsed into
a direct affine update when the subroutine body has a recognized linear form.

### Array Affine Loops

Loops that assign array elements from simple affine expressions can be executed
directly over packed numeric data.

Example shape:

```fortran
do i = 1, n
   y(i) = a*x(i) + b
end do
```

### Random Sum and Dot Loops

Certain loops that repeatedly call `random_number` and accumulate sums or dot
products are recognized and executed directly.

Example shapes:

```fortran
do i = 1, n
   call random_number(x)
   xsum = xsum + x
end do
```

```fortran
do i = 1, n
   call random_number(x)
   call random_number(y)
   xsum = xsum + x*y
end do
```

### Fannkuchredux Pattern

There is a specialized path for a recognized fannkuchredux benchmark program.
This path computes the benchmark result directly in C. It is useful for
experimentation with dispatch overhead, but it should be disclosed or disabled
with `--no-specialize` in general benchmark comparisons.

## What `--fast` Does Not Do

`--fast` currently does not:

- compile Fortran to machine code
- perform general bytecode compilation
- perform global optimization
- infer aliases from `intent(in)` or other attributes in a general optimizer
- vectorize arbitrary loops
- guarantee faster execution for every program

Unsupported patterns fall back to the regular interpreter path, so a program
can mix fast and normal execution.

## Benchmark Guidance

For transparent benchmark reports, include:

- whether `--fast` was used
- whether `--no-specialize` was used
- compiler and options used for native compilers
- whether compile time is included
- whether random-number sequences are expected to match

Reasonable comparisons include:

```powershell
.\ofort.exe x.f90
.\ofort.exe --fast x.f90
.\ofort.exe --fast --no-specialize x.f90
gfortran -O3 -march=native x.f90
```

For timing breakdowns:

```powershell
.\ofort.exe --fast --time-detail x.f90
```

For source-line hot spots:

```powershell
.\ofort.exe --fast --time-detail --profile-lines x.f90
```
