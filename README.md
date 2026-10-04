# ofort

`ofort` is a small offline interpreter for a practical subset of Fortran.
It is written in C and runs Fortran source directly from the command line or
from an interactive REPL. The project began as an extraction from
[CodeBench](https://github.com/yu314-coder/CodeBench) by [yu314-coder](https://github.com/yu314-coder) and is now organized as a
standalone command-line interpreter.

`ofort` is intended for experimentation, small examples, tests, and interpreter
development. It is not a production Fortran compiler.

## Project Layout

- `include/ofort.h` contains the public interpreter declarations shared by the
  C translation units.
- `src/main.c` contains command-line handling, the REPL, and user-facing
  diagnostics.
- `src/ofort.c` contains most of the parser, evaluator, runtime, and intrinsic
  implementation.
- `src/ofort_internal.h` contains internal declarations shared inside `src`.
- `src/ofort_values.c` contains value helper routines split out from the main
  interpreter implementation.
- `src/ofort_stats.c` and `include/ofort_stats.h` contain C-backed helper
  routines used by `ofort_statistics_mod` and related extension-module
  intrinsics.
- `src/ofort_fixed_form.c` and `include/ofort_fixed_form.h` contain the fixed
  source form to free source form converter used by `ofort`.
- `tests/test_ofort.py` contains the main pytest suite.
- `tests/cases` contains focused Fortran regression programs. Most stdout
  regression cases use a `name.f90` source file plus a sibling `name.out`
  expected-output file.
- `scripts/xofort.py` is a batch runner for trying many source files one at a
  time.
- `scripts/xofort_make.py` reads simple Fortran Makefiles, infers executable
  targets and their source dependencies, and runs those programs with `ofort`.
- `scripts/omat.py` is an experimental Octave-like subset translator
  that emits Fortran and can compile/run the generated program with
  `gfortran`.
- `scripts/omat_ide.py` is a worksheet-style GUI for `omat` with Octave-like
  input on the left, generated Fortran on the right, and output panes below.
- `scripts/opy.py` is an experimental Python/NumPy subset runner. It uses a
  local `xp2f.py` translator, rewrites supported NumPy idioms to Fortran, and
  runs the generated program with `ofort`.
- `scripts/opy_ide.py` is a worksheet-style GUI for `opy`. It can run the
  Python source, the generated Fortran, or both.
- `scripts/ofort_prune.py` is an experimental source-pruning helper driven by
  `ofort --unused-procs`.
- `scripts/og.py` compares `gfortran` and `ofort` output for one source file or
  a manifest of source files.
- `scripts/concat_manifest.py` concatenates a manifest of source files into one
  source file.
- `scripts/compile_manifest.py` compiles a manifest with `gfortran` by default
  or with `ifx`.
- `scripts/find_module.py` searches a manifest for the source file defining a
  module.
- `scripts/analyze_ofort_symbols.py` analyzes internal token/keyword handling
  and is used by the test suite.
- `tools/fixed2free.c` builds a small standalone fixed-form to free-form
  converter.
- `ofort_gui.py` is a small Tkinter GUI wrapper around `ofort.exe`.
- `xupdate.py` compares this working tree with a reference GitHub checkout,
  focusing on project source files and tests.
- `include/ofort_c_api.h` and `src/ofort_c_api.c` provide a small C ABI wrapper
  suitable for language bindings.
- `bindings/fortran` contains a Fortran `iso_c_binding` wrapper and demo
  program.
- `examples` contains small demonstration programs when present.

Generated files such as `ofort.exe`, `ofort.build`, `main*.f90`, compiler
objects, module files, and temporary `gfortran` executables are local build/run
artifacts and should not be committed.

## Current Status

The interpreter currently supports a growing practical Fortran subset. It is no
longer only a Fortran 90/95-style interpreter: the core remains small and
pragmatic, but `ofort` accepts selected features from Fortran 2003, 2008, 2018,
and 2023 where they are useful for real test programs. Coverage is
implementation-driven rather than standard-complete.

- scalar `INTEGER`, `REAL`, `DOUBLE PRECISION`, `COMPLEX`, `LOGICAL`, and
  `CHARACTER`
- arrays, array constructors, array sections, vector subscripts, allocatable
  arrays, allocatable scalars, and derived-type arrays
- modules, `use` imports, derived types, functions, subroutines, generic
  interfaces, optional arguments, `intent`, `pure` procedures, and elemental
  functions/subroutines
- `class` declarations, polymorphic-style dummy arguments, type-bound
  procedures, and basic dispatch for supported cases
- selected parameterized derived-type syntax and derived-type parameter
  handling used by the regression tests
- `block data`, `bind(c)` on supported declarations and common blocks, selected
  user-defined operators, and selected pointer/allocation features
- selected `iso_fortran_env` named constants such as `real64`, including
  `only` renaming
- `implicit none`, configurable implicit typing, declaration reordering in the
  REPL, assignment type checks, and diagnostics that include source lines
- `if`, `select case`, `do`, `do while`, labeled `do`, numbered `do`,
  numbered `do while`, `exit`, `cycle`, `goto`, computed `goto`, `forall`,
  `select rank`, `stop`, and `return`
- `format` statements, formatted `print`/`write`, `read`, `open`, `close`,
  `rewind`, `backspace`, `endfile`, internal I/O, simple external files, and
  simple unformatted stream I/O
- free source form plus automatic fixed source form conversion for `.f`,
  `.for`, and related fixed-form inputs
- simple preprocessing support for `#define` macro substitution in source files
- explicitly imported `ofort` extension modules, currently including
  `ofort_random_mod`, `ofort_la_mod`, `ofort_io_mod`, and
  `ofort_statistics_mod`; `stdlib_stats` is also recognized for a small
  compatibility subset of the Fortran stdlib statistics API, and
  `stdlib_linalg` and `stdlib_io` are recognized for small linear-algebra and
  text-I/O subsets
- command-line arguments via `command_argument_count`, `get_command_argument`,
  `get_command`, `get_environment_variable`, and the nonstandard `getarg`
- selected IEEE module support, including common `ieee_arithmetic` inquiries
  and constants used by the regression suite
- selected C interoperability support, including common `iso_c_binding`
  constants and helpers used by the regression suite
- allocatable utilities such as `allocated`, `allocate`, `deallocate`, and
  `move_alloc`

Selected Fortran 2023-visible features and library additions are present where
they were useful for tests, including degree-valued trigonometric intrinsics,
Bessel intrinsics, `select rank`, `new_line`, command/environment inquiries,
and additional `iso_fortran_env`, `iso_c_binding`, and IEEE module names.
Support for modern Fortran features is intentionally incremental rather than
complete. A feature being accepted in one tested form does not imply full
standard coverage for every edge case.

## ofort Extension Modules

`ofort` has optional nonstandard extension modules for interpreted workflows.
They are not required to run ordinary Fortran programs, and their procedure
names are not global intrinsics. Import them explicitly with `use` when needed.

Current extension modules:

- `ofort_random_mod`: random variates, including normal, uniform,
  exponential, lognormal, gamma, Poisson, binomial, Student t, Laplace,
  hyperbolic secant, and logistic generators
- `ofort_la_mod`: dense linear algebra helpers
- `ofort_lapack_mod`: optional compiled real64 LAPACK routines and `zgesv`,
  preserving LAPACK argument conventions and workspace queries
- `ofort_io_mod`: simple numeric text readers
- `ofort_statistics_mod`: vector, matrix, and column statistics
- `stdlib_stats`: compatibility subset mapping selected Fortran stdlib
  statistics names, including `mean`, `var`, `median`, `moment`, `cov`,
  `corr`, and limited PCA routines, to the same runtime routines as
  `ofort_statistics_mod`
- `stdlib_linalg`: compatibility subset mapping `eye`, `diag`, `det`, `eig`,
  `svd`, `qr`, `lu`, `pinv`, `cond`, `norm`, `triu`, `tril`, `kron`, `solve`,
  `inv`, `rank`, `chol`, `trace`, `outer_product`, `is_square`,
  `is_diagonal`, `is_symmetric`, and `is_invertible` to `ofort_la_mod`
  runtime routines
- `stdlib_io`: compatibility subset for `loadtxt` and `savetxt`
- `stdlib_stats_distribution_normal`: compatibility subset for `rvs_normal`,
  `pdf_normal`, and `cdf_normal`

See [docs/extension_modules.md](docs/extension_modules.md) for the full module
reference, including procedure lists, arguments, examples, and current
limitations.

Some old Fortran features are accepted for compatibility but reported as
obsolescent or nonstandard where appropriate. Examples include computed `goto`,
old alternate returns, and selected extension-style calls.

`REAL` and `DOUBLE PRECISION` are distinguished by type tag and kind, but both
are stored internally as C `double`.

Major modern Fortran features not currently implemented include coarrays and
`select type`. Some syntax from these areas may be diagnosed explicitly rather
than accepted.

## Intrinsics

Implemented intrinsics include common numeric, character, bit, inquiry, array,
random-number, and date/time routines, including:

`abs`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sind`,
`cosd`, `tand`, `asind`, `acosd`, `atand`, `atan2d`, `bessel_j0`,
`bessel_j1`, `bessel_jn`, `bessel_y0`, `bessel_y1`, `bessel_yn`, `exp`, `erf`,
`log`, `log10`, `gamma`, `hypot`, `mod`, `modulo`, `dim`, `aint`, `nint`,
`ceiling`, `floor`, `int`, `real`, `dble`, `dprod`, `kind`, `selected_int_kind`,
`selected_real_kind`, `huge`, `tiny`, `epsilon`, `digits`, `precision`, `range`,
`radix`, `nearest`, `spacing`, `rrspacing`, `scale`, `set_exponent`, `fraction`,
`exponent`, `len`, `new_line`, `trim`, `scan`, `verify`, `sum`, `product`,
`dot_product`, `matmul`, `maxval`, `minval`, `maxloc`, `minloc`, `count`, `any`,
`all`, `merge`, `pack`, `unpack`, `spread`, `eoshift`, `cshift`, `reshape`,
`shape`, `size`, `allocated`, `associated`, `lbound`, `ubound`, `rank`,
`is_contiguous`, `bit_size`, `btest`, `iand`, `ior`, `ieor`, `not`, `ibclr`,
`ibset`, `ibits`, `ishft`, `ishftc`, `maskl`, `maskr`, `transfer`,
`random_number`, `random_seed`, `cpu_time`, `date_and_time`, `system_clock`,
`command_argument_count`, `get_command`, `get_command_argument`, and
`get_environment_variable`.

Known missing intrinsics and future candidates are tracked in
`intrinsics_to_do.txt` when that file is present.

## Build

Build with the default compiler:

```powershell
make
```

Explicit compiler targets are also available:

```powershell
make gcc
make clang
```

The generated executable is `ofort.exe` on Windows.

For the optional compiled LAPACK backend, with gfortran on PATH and the local
`lapack_d.f90` present, run `make lapack`. An installed LAPACK/BLAS library can
also be used. See [the LAPACK module documentation](docs/extension_modules.md#ofort_lapack_mod)
for build options, the portable Fortran interfaces, and running `python_mod`
without interpreting LAPACK source.

`make` writes a small `ofort.build` file describing the compiler used for the
last build. That file is generated and should not be committed.

Build the standalone fixed-form converter:

```powershell
make fixed2free.exe
```

## Run

Run one source file:

```powershell
.\ofort.exe examples\xtry.f90
```

Pass program arguments after `--`:

```powershell
.\ofort.exe x.f90 -- alpha beta
```

Multiple positional source files are concatenated in command-line order before
execution:

```powershell
.\ofort.exe part1.f90 part2.f90
```

Run each file matched by a Windows glob as a separate program:

```powershell
.\ofort.exe --each "tests\cases\x*.f90"
.\ofort.exe --each --check "tests\cases\x*.f90"
.\ofort.exe --each --check --quiet --max-fail 10 "tests\cases\x*.f90"
```

Check syntax and semantic registration without running the program:

```powershell
.\ofort.exe --check x.f90
```

Resolve modules for a main source file from the same directory. If the main
program uses module `m`, `ofort` looks for `m.f90`, `m_mod.f90`, and
`m_module.f90`, with `_mod` and `_module` stripped when appropriate:

```powershell
.\ofort.exe --dep c:\path\to\xmain.f90
.\ofort.exe --each --dep "c:\path\to\*_test.f90"
```

Built-in modules such as `iso_fortran_env`, `iso_c_binding`,
`ieee_arithmetic`, `ieee_exceptions`, and `ieee_features` are not looked up on
disk.

Compare `ofort` output with `gfortran`:

```powershell
.\ofort.exe --check-gfortran x.f90
.\ofort.exe --dep c:\path\to\xmain.f90 --check-gfortran
```

Enable execution timing:

```powershell
.\ofort.exe --time x.f90
.\ofort.exe --time-detail x.f90
```

In `--each --quiet --time` mode, `ofort` prints only the final summary and one
total elapsed time line.

Print execution time by source line:

```powershell
.\ofort.exe --profile-lines x.f90
```

Print execution time by user procedure:

```powershell
.\ofort.exe --profile-procs x.f90
.\ofort.exe --fast --profile-procs x.f90
```

Enable interpreter fast paths:

```powershell
.\ofort.exe --fast x.f90
```

See [optimizations.md](optimizations.md) for the current `--fast`
implementation and its limitations. Use `--no-specialize` with `--fast` to
disable specialized pattern/program fast paths while keeping the general fast
mode enabled.

For large source files with a small main program, reachable-source pruning can
skip unused modules and procedures before execution:

```powershell
.\ofort.exe --reachable --fast x.f90
.\ofort.exe --write-reachable temp.f90 x.f90
```

`--write-reachable file` writes the pruned source and implies `--reachable`.
The emitted source is intended to be compilable Fortran when the pruning
analysis has enough information. It is a debugging and reduction aid, not a
full whole-program optimizer.

To list unreachable procedures in a machine-readable form:

```powershell
.\ofort.exe --unused-procs x.f90
python .\scripts\ofort_prune.py x.f90 -o pruned.f90
```

Cache normalized/free-form source for repeated runs:

```powershell
.\ofort.exe --cache x.f90
```

Call a precompiled native subroutine for a hot kernel:

```powershell
.\ofort.exe --native stats=mean_sd_native.dll:stats_c mean_sd.f90 xmean_sd.f90 --fast
```

The same mapping can be placed in source as an `ofort` directive comment, which
ordinary Fortran compilers ignore:

```fortran
!$ofort native stats=mean_sd_native.dll:stats_c
```

The initial native ABI is intentionally narrow. `r8arr_r8arr` maps an
interpreted call `stats(x, y)` to a C-compatible symbol with arguments
`(int *nx, double *x, int *ny, double *y)`, where `x` and `y` are rank-1
`real(8)` arrays. This covers both different-size and same-size output arrays.
Scalar outputs can be packed into `y`. `r8arr_r8` maps a scalar-valued function
call such as `xmean = mean(x)` to a native symbol with arguments
`(int *nx, double *x, double *y)`. `r8arr_r8arr_r8` maps a two-vector scalar
function such as `c = corr(x, y)` to
`(int *nx, double *x, int *ny, double *y, double *z)`. `r8mat_r8mat` maps a
matrix transform call `call corrmat(x, y)` to
`(int *nx1, int *nx2, double *x, int *ny1, int *ny2, double *y)`. `i4_r8arr`
maps a vector-valued function such as `x = rnorm(n)` to
`(int *n, int *ny, double *y)`, where `ofort` allocates the returned rank-1
`real(8)` array of length `n`.

Trace assignment values:

```powershell
.\ofort.exe --trace-assign x.f90
```

`--trace-assign` prints the value assigned by each executed assignment
statement. In the interactive REPL, top-level assignment lines run immediately
when this mode is enabled, so a line such as `n = 2**5` prints `32` without
requiring `.` or `.run`.

Enable REPL block completion:

```powershell
.\ofort.exe --auto-end
```

In interactive mode, `--auto-end` inserts matching `end ...` lines for clear
block openers such as `program main`, `do`, `if (...) then`, `module m`,
`subroutine s(...)`, and `type :: t`. Subsequent input is inserted inside the
innermost generated block. Typing the matching `end ...` line moves out of that
generated block instead of adding a duplicate.

By default, `ofort` rejects undeclared variables, even though historical
Fortran implicit typing is standard-conforming. To allow the classic rule where
names beginning with I-N are integers and other names are real:

```powershell
.\ofort.exe --implicit-typing x.f90
```

The default language mode is pragmatic legacy compatibility. To reject known
nonstandard extensions where `ofort` can identify them, use:

```powershell
.\ofort.exe --std=f2023 x.f90
```

`--std=f2023` is a diagnostic mode, not a claim of complete Fortran 2023
coverage.

Warnings are enabled by default. Use `-w` to suppress them:

```powershell
.\ofort.exe -w x.f90
```

Use `-Werror` or `--warn-error` to make warnings fail the run:

```powershell
.\ofort.exe -Werror x.f90
.\ofort.exe --warn-error x.f90
```

Reads of uninitialized declared variables are rejected by default. This catches
many bugs early. To allow such reads or to give otherwise uninitialized
variables deterministic values:

```powershell
.\ofort.exe --no-check-uninitialized x.f90
.\ofort.exe --init-int 0 --init-real nan --init-char "?" x.f90
```

### Fixed Source Form

`ofort` accepts free source form by default and automatically treats common
fixed-form extensions such as `.f` and `.for` as fixed source form. Use
`--fixed-form` or `--free-form` to override auto-detection:

```powershell
.\ofort.exe --fixed-form oldcode.f
.\ofort.exe --free-form modern.f90
```

The internal converter is shared with the standalone `fixed2free.exe` tool:

```powershell
make fixed2free.exe
.\fixed2free.exe oldcode.f > oldcode.f90
```

To save the converted free-form source next to the original input while running
`ofort`, use:

```powershell
.\ofort.exe --save-free oldcode.f
```

## Batch Runner

The Python batch runner processes a file glob one source at a time:

```powershell
python .\scripts\xofort.py "tests\cases\*.f90"
python .\scripts\xofort.py --check "tests\cases\*.f90"
python .\scripts\xofort.py --limit 5 "tests\cases\*.f90"
python .\scripts\xofort.py --timeout 30 "tests\cases\*.f90"
python .\scripts\xofort.py --max-lines 100 "tests\cases\*.f90"
python .\scripts\xofort.py --quiet "tests\cases\*.f90"
python .\scripts\xofort.py --filter "gfortran -std=f95" "tests\cases\*.f90"
python .\scripts\xofort.py --dep --fast --timeout 30 "c:\work\*_test.f90"
python .\scripts\xofort.py --manifests "c:\work\*files.txt" --run-dir manifest
python .\scripts\xofort.py --manifests @manifests.txt --skip-lines 100 --max-fail 1
```

`--quiet` reports only files that `ofort` does not handle. `--filter` runs the
given command with the source file appended and skips files for which that
command fails.

`--manifests` treats each matched file as a manifest and invokes `ofort` with
`@manifest`. This is useful for projects organized as file lists rather than a
single source file. `--run-dir manifest` runs each manifest from the manifest's
directory so relative data-file paths are resolved in the same place as the
source list. `--timeout-ok` reports timeouts without counting them against
`--max-fail`.

With `--check-gfortran`, `xofort.py` invokes `gfortran -fsyntax-only` only for
cases that failed under `ofort`; failures rejected by `gfortran` do not count
against `--max-fail`.

## Makefile Runner

`scripts\xofort_make.py` is a lightweight Makefile-aware runner. It parses
simple variable assignments and target dependencies, infers executable targets,
recursively follows object-file dependencies, and runs each inferred program
with `ofort`.

List inferred programs:

```powershell
python .\scripts\xofort_make.py c:\path\to\Makefile --list
```

Run one target:

```powershell
python .\scripts\xofort_make.py c:\path\to\Makefile --target xprog.exe
python .\scripts\xofort_make.py c:\path\to\Makefile --target xprog.exe --fast
```

When a long run times out, stream program output as it is produced so the last
printed line shows how far it got:

```powershell
python .\scripts\xofort_make.py c:\path\to\Makefile --target xprog.exe --fast --live-output
```

Write the inferred source list for one target into a single source file:

```powershell
python .\scripts\xofort_make.py c:\path\to\Makefile --target xprog.exe --write-source xprog_all.f90
```

`--write-source` is a concatenation aid. It is distinct from
`ofort --write-reachable`, which tries to remove unreachable code.

## omat Prototype

`scripts\omat.py` is an experimental companion prototype for translating a
small Octave-like numerical subset to Fortran. It is separate from
`ofort` itself. The first version targets simple scalar, rank-1 vector, and
small rank-2 matrix workflows:

- assignments such as `x = [1, 2, 3]`
- matrix literals such as `A = [1 2; 3 4]`
- immediate expression printing and `disp(expr)`
- `for i = 1:n ... end` loops
- elementwise operators `.*`, `./`, and `.^`
- scalar power with `^`; for arrays, use `.^` because Octave `^` means
  matrix power, which `omat` does not implement yet
- matrix multiplication for simple identifier expressions, such as `A * x`
- `reshape(x,m,n)` to form a 2D array and `A(:)` to flatten a matrix in
  column-major order
- `rand(n)`, `rand(n,1)`, `rand(m,n)`, `zeros(n)`, `zeros(m,n)`, `ones(n)`,
  `ones(m,n)`, and `linspace(a,b,n)`
- `equicor(n, rho)` for an `n` by `n` equicorrelation matrix with ones on the
  diagonal and `rho` elsewhere
- Octave-style random distribution names backed by `ofort_random_mod`,
  including `randn`, `normrnd`, `unifrnd`, `exprnd`, `lognrnd`, `gamrnd`,
  `poissrnd`, `binornd`, `trnd`, `laprnd`, `sechrnd`, and `logisticrnd`
- Octave-style dense linear algebra names backed by `ofort_la_mod`, including
  `eye`, `diag`, `trace`, `det`, `eig`, `svd`, `qr`, `lu`, `pinv`, `cond`,
  `norm`, `triu`, `tril`, `kron`, `inv`, `rank`, `chol`, `solve`, and
  `mldivide`
- common reductions and functions such as `sum`, `mean`, `std`, `var`,
  `median`, `skewness`, `kurtosis`, `rms`, `mad`, `quantile`, `prctile`,
  `iqr`, `cumsum`, `movmean`, `zscore`, `cov`, `corr`, `corrcoef`, `min`,
  `max`, `sqrt`, `sin`, `cos`, `exp`, and `log`

For matrix `A`, `sum(A)` and `sum(A,1)` return column sums, while `sum(A,2)`
returns row sums. Full Octave matrix semantics are not implemented.
Programs that use the `ofort_la_mod`-backed linear algebra functions are run
with `ofort`, not `gfortran`, because those algorithms are interpreter
extensions.

Generate Fortran without running:

```powershell
python .\scripts\omat.py .\examples\omat_stats.m -o omat_stats.f90
```

Translate, compile with `gfortran`, and run:

```powershell
python .\scripts\omat.py .\examples\omat_stats.m
```

Generate both the `ofort`-oriented and generic Fortran translations:

```powershell
python .\scripts\omat.py x.m --ofort-out x_ofort.f90 --generic-out x_generic.f90
```

Compile the generic Fortran with `gfortran -Wall -Wextra`:

```powershell
python .\scripts\omat.py x.m --compile
```

With no source file, `omat` starts a small REPL:

```powershell
python .\scripts\omat.py
```

In the REPL, each complete top-level line is translated to Fortran and run
with `ofort` immediately. As in Octave, an assignment without a trailing
semicolon prints the assigned value, while a trailing semicolon suppresses
output:

```text
omat> x = 10
10.0
omat> y = x + 5;
omat> y
15.0
```

Random values entered in the REPL are materialized into the stored buffer, so a
later expression such as `sum(x)` reuses the values created by `x = rand(n)`
instead of generating a new vector.
Long vector and matrix assignment results are summarized in the REPL display;
the full values are still stored in the generated source.

If a line is rejected by the translator or by `ofort`, the REPL reports the
error and does not keep that line in the buffer.

REPL commands are:

```text
run      translate and run the current buffer with ofort
.        same as run
fortran  print the generated Fortran for the current buffer
list     list the current input buffer
clear    clear the buffer
quit     exit
```

This is not an Octave-compatible interpreter. It is a starting point for
numerical subset experiments, with Octave-like syntax on the front end
and generated Fortran on the back end.

`omat` is not affiliated with GNU Octave or MathWorks. MATLAB is a trademark or
registered trademark of The MathWorks, Inc.

Run only the `omat` tests with:

```powershell
python -m pytest -q -c pytest_omat.ini
```

## opy Prototype

`scripts\opy.py` is an experimental Python/NumPy-to-Fortran runner. It is
intended for small numerical Python examples, interactive experiments, and
coverage work. It is not a general Python implementation.

`opy` uses an external translator, `xp2f.py`, to translate a complete accepted
session to Fortran, then patches and inlines the helper routines needed by the
currently supported NumPy subset. By default it looks for:

```text
c:\python\Python-to-Fortran\xp2f.py
```

Use `--xp2f` to point at a different copy.

Run a Python source file:

```powershell
python .\scripts\opy.py x.py
```

Write the generated Fortran:

```powershell
python .\scripts\opy.py x.py -o x_from_python.f90
```

Generated helper procedures include brief trailing comments by default, for
example `function rnorm(n) result(x)  ! n standard normal variates`.
Use `--no-explain` to omit these pedagogical comments.

With no source file, `opy` starts a REPL:

```powershell
python .\scripts\opy.py
```

In the REPL, imports and accepted lines are accumulated into a Python source
buffer. A bare expression is treated like an interactive Python expression and
printed. For example:

```text
opy> import numpy as np
opy> x = np.arange(5)
opy> np.sum(x)
10
opy> fortran
```

The `fortran` command prints the generated Fortran. On exit, `opy` writes
`opy_session.f90` and `generic_session.f90` by default; use `--no-save-session`
to suppress that.

Currently supported NumPy-oriented idioms include:

- `import numpy as np` using any alias, plus selected `from numpy import ...`
  forms
- array constructors such as `np.array`, `np.arange`, `np.linspace`,
  `np.zeros`, and `np.ones`
- common reductions and elementals such as `np.sum`, `np.mean`, `np.std`,
  `np.var`, `np.min`, `np.max`, `np.sqrt`, `np.sin`, `np.cos`, `np.exp`,
  `np.log`, `np.cumsum`, and `np.diff`
- `np.random.uniform` and `np.random.normal`, including scalar forms and
  `size=` vector forms
- simple `for i in range(...)` loops and `if` blocks in the subset handled by
  the translator

Unsupported standard-library modules that are outside the current numerical
subset are diagnosed before translation when used. Examples include `re`,
`json`, `csv`, `os`, `pathlib`, `subprocess`, `datetime`, `time`, `glob`, and
related filesystem, process, network, and data-structure modules. `math`,
`statistics`, and `random` are intentionally not rejected as modules because
parts of those APIs can be mapped or may be mapped later.

Run only the `opy` tests with:

```powershell
python -m pytest -q tests\test_opy.py
```

## GUI

`ofort_gui.py` provides a small Tkinter front end around the command-line
interpreter. It does not link to the C code directly; it writes the editor
contents to a temporary Fortran file, invokes `ofort`, and displays the
captured output. It can also call external compilers when they are installed
and available on `PATH`.

Run it with:

```powershell
python .\ofort_gui.py
```

Current GUI features include:

- source editor with 4-space auto-indentation for common `if`, `do`, `select`,
  `where`, and related blocks
- automatic insertion of matching `()`, `[]`, single quotes, and double quotes;
  these editor conveniences can be disabled with internal constants near the
  top of `ofort_gui.py`
- conservative block completion on Enter for forms such as `program`, `module`,
  `subroutine`, `function`, `do`, `if ... then`, `select`, `where`,
  `associate`, `block`, `interface`, and `type :: name`
- syntax coloring for common Fortran keywords, declaration words, intrinsics,
  strings, comments, and numbers
- open/save support for Fortran source files
- checkboxes for `--trace-assign`, `--implicit-typing`, `--std=f2023`, and
  `--fast`
- run buttons for `ofort`, `gfortran`, `ifx`, and LFortran
- check/compile-only buttons: `Check ofort`, `Compile gfortran`, `Compile ifx`,
  and `Compile LFortran`
- stdout, stderr, assignment-trace, and problems panes, with the active pane
  switching automatically after run/check/compile actions
- clickable problem diagnostics that jump to the reported source line
- compiler output cleanup for common ANSI color sequences emitted by tools such
  as LFortran
- elapsed-time reporting for check, compile, run, and total time

The GUI should run on Windows, macOS, and Linux when Python includes Tkinter and
an `ofort` executable is either next to `ofort_gui.py` or available on `PATH`.
External compiler buttons require the corresponding compiler executable
(`gfortran`, `ifx`, or `lfortran`) to be installed and available on `PATH`.

### omat IDE

`scripts\omat_ide.py` is a worksheet-style GUI for the Octave-like
translator:

```powershell
python .\scripts\omat_ide.py
```

The left pane contains Octave-like source, the right pane shows the
generated Fortran, and the bottom pane shows run output. It can run each
accepted line immediately, generate either `ofort`-oriented or generic Fortran,
and run with `ofort --fast` by default. Use `--generic` to start in generic
Fortran mode and `--no-fast` to start with plain `ofort`.

`scripts\omat2_ide.py` is a newer omat IDE built on the shared translator IDE
base in `scripts\fortran_ide_base.py`:

```powershell
python .\scripts\omat2_ide.py
python .\scripts\omat2_ide.py x.m
python .\scripts\omat2_ide.py --source x.m
```

The shared base provides the common source pane, generated Fortran pane,
compiler selector, source/Fortran run buttons, generic/ofort Fortran mode,
manual Fortran editing, help window, and output timing. It is intended to be
reused by future source-to-Fortran IDEs, such as an R-to-Fortran prototype.

### ofort Fortran IDE

`scripts\ofort_ide.py` is a worksheet-style IDE for comparing ofort-oriented
Fortran with best-effort generic Fortran:

```powershell
python .\scripts\ofort_ide.py
python .\scripts\ofort_ide.py x.f90
python .\scripts\ofort_ide.py --source x.f90
```

The left pane contains ofort-oriented Fortran, and the right pane contains a
generic Fortran translation. The first translation pass preserves standard
Fortran and rewrites selected ofort helper-module imports. Currently it can
replace common `ofort_random_mod` uses with a portable `random_mod`; unsupported
ofort-specific modules are left in place with a warning comment.

The same first-pass transpiler is available on the command line:

```powershell
python .\scripts\ofort_to_generic.py x.f90 -o x_generic.f90
python .\scripts\ofort_to_generic.py x.f90
```

### Fortran Compare IDE

`scripts\fortran_compare_ide.py` is a side-by-side IDE for running the same
generic Fortran source with two compiler backends:

```powershell
python .\scripts\fortran_compare_ide.py
python .\scripts\fortran_compare_ide.py x.f90
python .\scripts\fortran_compare_ide.py --compiler-a "ofort --fast" --compiler-b gfortran
```

It has one Fortran source pane and two output panes. Each output pane has its
own compiler selection, elapsed-time label, and captured output. Supported
backends are `ofort --fast`, `ofort`, `gfortran`, `gfortran -O2`,
`gfortran -O3`, `ifx`, `ifx /O2`, and `lfortran`. The IDE can run either side,
run both, show a unified output diff, format floating-point output with a
selected number of decimals, and save or restore JSON sessions.

### opy IDE

`scripts\opy_ide.py` is the analogous worksheet-style GUI for Python/NumPy:

```powershell
python .\scripts\opy_ide.py
python .\scripts\opy_ide.py x.py
python .\scripts\opy_ide.py --source x.py
```

It has Python input on the left, generated Fortran on the right, and output
panes below. Current features include:

- syntax coloring for Python, dotted NumPy calls such as `np.sum`, and
  generated Fortran
- run buttons for `Run Python`, `Run Fortran`, and `Run Both`
- a `Help` window summarizing workflow, compiler modes, diagnostics, and dot
  commands
- a compiler selector for `ofort --fast`, `ofort`, `gfortran`,
  `gfortran -O2`, `gfortran -O3`, `ifx`, `ifx /O2`, and `lfortran`
- a `Profile procedures` checkbox for `ofort` runs, which adds
  `--profile-procs`
- separate Python and Fortran output panes with per-pane elapsed-time labels
- a diagnostics pane, revealed when the `opy>` entry receives an ofort dot
  command such as `.vars`, `.info`, `.shapes`, `.sizes`, or `.stats`
- autocomplete suggestions for safe inspection dot commands when the `opy>`
  entry starts with `.`
- an `Immediate run` mode, enabled by default, for worksheet-style execution as
  complete lines are entered
- automatic indentation after Python block headers such as
  `for i in range(5):`
- partial Fortran previews for incomplete `for`, `if`, and `while` blocks
- an `Explain helpers` checkbox that adds or removes brief comments on
  generated Fortran helper procedures
- an `Edit Fortran` mode for manually editing generated Fortran, plus
  `Regenerate` to replace manual edits from the Python source

Use `--source` or a positional source filename to open Python code at startup.
Use `--compiler` to choose the initial Fortran backend, `--no-immediate` to
start with immediate execution disabled, and `--no-fast` to start with plain
`ofort`.

## Fortran Binding

`ofort` also includes an experimental Fortran binding. The binding is built in
two layers:

- `include/ofort_c_api.h` and `src/ofort_c_api.c` expose a small stable C ABI
  with opaque interpreter handles.
- `bindings/fortran/ofort_binding.f90` wraps that C ABI using
  `iso_c_binding`.

The Fortran wrapper provides an `ofort_interpreter` derived type with methods
such as:

```fortran
use ofort_binding, only: ofort_interpreter
type(ofort_interpreter) :: interp
integer :: rc

call interp%create()
rc = interp%execute("integer :: n = 2; print*,n**5")
write (*, '(a)', advance='no') interp%output()
call interp%destroy()
```

The current demo is `bindings/fortran/demo_eval.f90`. It creates an
interpreter, executes a small source string, prints captured `ofort` output,
then enables assignment tracing and prints the captured trace output. It also
defines an interpreted Fortran function and calls it directly from compiled
Fortran with the typed `call_real1` wrapper:

```fortran
rc = interp%execute("real function f(x); real :: x; f = x*x + 1; end")
y = interp%call_real1("f", 3.0d0)
```

Build the demo from the repository root with:

```powershell
make -f bindings\fortran\makefile
```

Run it with:

```powershell
.\bindings\fortran\demo_eval.exe
```

Expected output:

```text
32
56
10.000000000000000
```

The binding is intended for embedding `ofort` in Fortran programs for
experimentation, dynamic evaluation, and small interpreter-driven workflows. It
currently exposes a minimal typed direct-call API for invoking an interpreted
`real`/`double precision` function of one real argument. Broader direct-call
support, such as integer, logical, character, multi-argument, and array
signatures, would require additional typed wrappers and argument/result
marshalling.

## Benchmarks

Benchmark helpers are in `scripts\bench_ofort.py` and the `benchmarks`
directory when present. The benchmark script can compare `ofort`, `ofort
--fast`, `gfortran`, `ifx`, and `lfortran`, depending on which tools are
installed.

Generate or resize the benchmark programs with one base problem-size parameter:

```powershell
python .\scripts\generate_benchmarks.py --size 1000000
python .\scripts\generate_benchmarks.py --size 5000000 --list
```

The generator writes the `benchmarks\xbench_*.f90` files. Each benchmark derives
its own `n` from the base size so that the current mix of array and scalar-loop
tests remains roughly balanced. Increase `--size` until benchmark run times are
large enough to be meaningful on your machine.

Example:

```powershell
python .\scripts\bench_ofort.py --ofort-only
python .\scripts\bench_ofort.py --ofort-only --gfortran
```

## Interactive Mode

With no file argument, `ofort` starts a REPL. The default prompt is `> `; use
`--prompt text` or `.prompt text` to change it. Type Fortran source at the
prompt and use dot commands to run, edit, inspect, and save the current source
buffer. The REPL assumes `implicit none` by default for interactive source
unless you enter an explicit `implicit` statement.

By default, the REPL performs immediate checks when source lines are entered so
many mistakes are reported before `.`, `.run`, or compiler commands are used.
Use `--defer-check` when pasting or drafting incomplete code and you want source
lines to be accepted first and checked only when the buffer is run.

Use `--autorun` when you want complete top-level executable lines to run the
current source immediately after entry, without typing `.` on the next line.
Declarations and block openers are just added to the buffer. `--autorun` is
ignored when `--defer-check` is also active.

The REPL can also save and restore simple runtime state. `.save-state file`
writes an inspectable text file containing the current source buffer plus
generated declarations and assignments for simple visible variables. `.load-state
file` restores that source and those values. Version 1 is intended for scalars
and simple arrays of intrinsic types; it preserves `parameter` constants and
declared real/integer kind where that information is available. Pointers, open
files, and derived-type object graphs are not serialized.

For large `real(kind=8)` arrays, `.save-state file --binary-arrays` writes one
sidecar binary file per large array in a sibling `*_data` directory and emits
restore code that reads the array with stream unformatted I/O. Arrays with at
least 1,000,000 elements use binary sidecars by default; use
`--array-threshold n` to change that cutoff. Small arrays and scalars remain in
the text state file.

Common commands:

```text
.        run the current source and continue
.ofort   run the current source with ofort; accepts options such as --fast
.gfortran run with gfortran; external compiler options are forwarded
.ifx     run with ifx
.lfortran run with LFortran
.g95     run with g95
.timec   time compiler runs; for example .timec 3 ofort --fast; gfortran -O3
.run     run; .run n repeats n times; use -- before program arguments
.runq    run and quit
.time    run and print elapsed-time statistics; .time n repeats n times
.quit    quit and autosave the source buffer
.quit!   quit without saving
.save    save the source buffer
.saveq   save the source buffer and quit
.save-state save source plus simple variable values to a replayable state file
.save-state file --binary-arrays save large real arrays as binary sidecars
.saveq-state save state and quit
.load-state restore source plus simple variable values from a state file
.clear   clear the current source
.prompt  change the prompt text
.del     delete a line or range, such as .del 3, .del 2:4, .del :3, .del 4:
.ins     insert a source line before a line number
.rep     replace a source line
.rename  rename a variable token throughout the editable source
.list    list the current source
.list -n list source without line numbers
.group-decl group simple declarations by type
.unused  list simple declarations that appear unused
.undecl  remove declarations by variable name
.drop-unused remove simple unused declarations
.decl    list declaration lines
.vars    list variable values
.info    list concise declaration-style variable information
.shapes  list array shapes
.sizes   list array sizes
.stats   list numeric array statistics
.load    load a file into the current source
.load-run load a file, run it once, and keep editing
```

The shortcuts `q` and `quit` also quit and autosave, unless `q` or `quit` has
been defined as a variable in the current source buffer. Use `.quit!` for an
explicit no-save exit. `.saveq file.f90 --overwrite` saves to a specific file
and permits replacing an existing file.

External compiler commands write the current standard Fortran source to a
temporary file, invoke the selected compiler, and display the compiler's output.
For compile-only checks, pass `-c`, for example `.gfortran -O3 -c`.
Semicolon-separated compiler commands run in sequence:

```text
.ofort --fast; .gfortran -O3; .ifx -O3
```

`.timec` times the same style of compiler command list. Inside `.timec`, the
leading dot is optional:

```text
.timec 3 ofort --fast; gfortran -O3 -march=native; ifx -O3
```

The `.timec` table reports average compile/link time, run time, total time, and
status. For `.ofort`, compile time is shown as `-` because no native
compile/link phase is used. External compiler segments in one `.timec` command
share a single temporary source file.

When `.load file.f90`, `.load-run file.f90`, `--load file.f90`, or
`--load-run file.f90` loads a complete program, the final `end` line is held
aside so new input is inserted before the end of the program. The held line is
restored when running or autosaving.

In interactive mode only, a bare expression line is evaluated immediately
against the current source buffer and prints its value. For example, after
entering `x = 3`, a line containing only `x` displays `3` immediately. Bare
expression lines are not added to the source buffer.

The REPL also accepts two convenience forms for quick interactive work:

```fortran
let x = 2.5
const n = 100
const v(3) = [10, 20, 30]
```

`let` infers a scalar type from the right-hand side, appends a standard
declaration, and then appends an assignment. For example, `let x = 2.5` is
stored as ordinary Fortran source equivalent to:

```fortran
real :: x
x = 2.5
```

`const` infers a named constant and stores a standard `PARAMETER` declaration.
For example, `const n = 100` is stored as:

```fortran
integer, parameter :: n = 100
```

Use `let` only for the first definition of a variable; after that, use normal
assignment such as `x = 3.0`. To change a named constant during a session, use
`reconst name = value`, which replaces the earlier parameter declaration in the
editable source buffer. These forms are REPL conveniences, not Fortran syntax,
and saved/autosaved source uses standard Fortran declarations.

Other REPL source conveniences include:

- `real x(n)` is stored as standard `real :: x(n)` for simple declarations
- `print x, y` is stored as standard `print *, x, y`
- quoted format strings such as `print "(f8.3)", x` are left unchanged
- mixed-length character constructors assigned interactively can be rewritten
  with an explicit `character(len=...) ::` constructor when safe

With `--auto-end`, the REPL can insert matching block terminators:

```text
> program main
> integer :: i
> do i = 1, 3
> print *, i
> end do
> end program main
```

The explicit `end do` and `end program main` lines above move out of generated
blocks instead of adding duplicates.

The REPL preflights source after each entered program line. Lines with syntax
errors, such as malformed declarations, are rejected and are not kept in the
editable source buffer.

When an interactive session exits with a non-empty source buffer, the buffer is
saved automatically as `main.f90`, or `main1.f90`, `main2.f90`, and so on if
earlier names already exist.

Those `main*.f90` files are autosave artifacts. Move or delete them when no
longer needed; they are not intended to be committed.

## Test

```powershell
pytest -q
```

The test suite is intentionally small-program oriented. New language features
are usually added by creating a focused `tests/cases/x*.f90` source and a
matching `.out` file.

Only `tests/cases/*.f90` files with a sibling UTF-8 text `.out` file are
collected as simple stdout regression cases. Files without an expected-output
file may still be used by targeted tests in `tests/test_ofort.py`.

Some tests compare behavior with `gfortran` or exercise local files. The core
test suite should pass with:

```powershell
make
pytest -q
```

## Local Check Helpers

`github_check.bat` is a Windows helper that clones the GitHub repository into
`C:\github\ofort` by default, or into the directory supplied as its first
argument, then runs `make gcc` and `pytest -q` there.

```cmd
github_check.bat
github_check.bat C:\github\ofort_temp
```

`gitcheck.bat` is a local Windows `cmd.exe` sanity check for this working copy.
It clones the committed `HEAD` into `ofort_build_check`, builds it, and runs the
tests. It is useful for catching files that were edited locally but not
committed. It is not required for portable builds.

`xupdate.py` compares this working tree with a reference checkout, by default
`C:\github\ofort`, and reports important project files that are missing or
different. It is read-only.

```cmd
python xupdate.py --notemp
python xupdate.py --notemp --flat
```
