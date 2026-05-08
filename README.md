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
- `tests/test_ofort.py` contains the main pytest suite.
- `tests/cases` contains focused Fortran regression programs. Most stdout
  regression cases use a `name.f90` source file plus a sibling `name.out`
  expected-output file.
- `scripts/xofort.py` is a batch runner for trying many source files one at a
  time.
- `ofort_gui.py` is a small Tkinter GUI wrapper around `ofort.exe`.
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
pragmatic, but `ofort` accepts selected Fortran 2003/2008/2018-era features
where they are useful for real test programs. Coverage is implementation-driven
rather than standard-complete.

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
  `stop`, and `return`
- `format` statements, formatted `print`/`write`, `read`, `open`, `close`,
  `rewind`, internal I/O, simple external files, and simple unformatted stream
  I/O
- simple preprocessing support for `#define` macro substitution in source files
- explicitly imported `ofort` extension modules, currently including
  `ofort_random_mod`, `ofort_la_mod`, `ofort_io_mod`, and
  `ofort_statistics_mod`
- command-line arguments via `command_argument_count`, `get_command_argument`,
  and the nonstandard `getarg`
- allocatable utilities such as `allocated`, `allocate`, `deallocate`, and
  `move_alloc`

Support for modern Fortran features is intentionally incremental rather than
complete. A feature being accepted in one tested form does not imply full
standard coverage for every edge case.

## ofort Extension Modules

`ofort` has optional nonstandard extension modules for interpreted workflows.
They are not required to run ordinary Fortran programs, and their procedure
names are not global intrinsics. Import them explicitly with `use` when needed.

Current extension modules:

- `ofort_random_mod`: normal random variates
- `ofort_la_mod`: dense linear algebra helpers
- `ofort_io_mod`: simple numeric text readers
- `ofort_statistics_mod`: vector, matrix, and column statistics

See [docs/extension_modules.md](docs/extension_modules.md) for the full module
reference, including procedure lists, arguments, examples, and current
limitations.

Some old Fortran features are accepted for compatibility but reported as
obsolescent or nonstandard where appropriate. Examples include computed `goto`,
old alternate returns, and selected extension-style calls.

`REAL` and `DOUBLE PRECISION` are distinguished by type tag and kind, but both
are stored internally as C `double`.

## Intrinsics

Implemented intrinsics include common numeric, character, bit, inquiry, array,
random-number, and date/time routines, including:

`abs`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`,
`log`, `log10`, `gamma`, `hypot`, `mod`, `modulo`, `dim`, `aint`, `nint`,
`ceiling`, `floor`, `int`, `real`, `dble`, `dprod`, `kind`, `selected_int_kind`,
`selected_real_kind`, `huge`, `tiny`, `epsilon`, `digits`, `precision`, `range`,
`radix`, `nearest`, `spacing`, `rrspacing`, `scale`, `set_exponent`, `fraction`,
`exponent`, `len`, `trim`, `scan`, `verify`, `sum`, `product`, `maxval`,
`minval`, `maxloc`, `minloc`, `count`, `any`, `all`, `merge`, `pack`, `unpack`,
`spread`, `eoshift`, `cshift`, `reshape`, `shape`, `size`, `allocated`,
`associated`, `lbound`, `ubound`, `bit_size`, `btest`, `iand`, `ior`, `ieor`,
`ibclr`, `ibset`, `ibits`, `ishft`, `ishftc`, `maskl`, `maskr`, `random_number`,
`random_seed`, `cpu_time`, `date_and_time`, and `system_clock`.

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

`make` writes a small `ofort.build` file describing the compiler used for the
last build. That file is generated and should not be committed.

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
```

Check syntax and semantic registration without running the program:

```powershell
.\ofort.exe --check x.f90
```

Compare `ofort` output with `gfortran`:

```powershell
.\ofort.exe --check-gfortran x.f90
```

Enable execution timing:

```powershell
.\ofort.exe --time x.f90
.\ofort.exe --time-detail x.f90
```

Print execution time by source line:

```powershell
.\ofort.exe --profile-lines x.f90
```

Enable interpreter fast paths:

```powershell
.\ofort.exe --fast x.f90
```

See [optimizations.md](optimizations.md) for the current `--fast`
implementation and its limitations. Use `--no-specialize` with `--fast` to
disable specialized pattern/program fast paths while keeping the general fast
mode enabled.

Trace assignment values:

```powershell
.\ofort.exe --trace-assign x.f90
```

`--trace-assign` prints the value assigned by each executed assignment
statement. In the interactive REPL, top-level assignment lines run immediately
when this mode is enabled, so a line such as `n = 2**5` prints `32` without
requiring `.` or `.run`.

By default, `ofort` follows historical Fortran implicit typing, where names
beginning with I-N are integers and other names are real. To require explicit
declarations unless an `implicit` statement says otherwise:

```powershell
.\ofort.exe --no-implicit-typing x.f90
```

Warnings are enabled by default. Use `-w` to suppress them:

```powershell
.\ofort.exe -w x.f90
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
```

`--quiet` reports only files that `ofort` does not handle. `--filter` runs the
given command with the source file appended and skips files for which that
command fails.

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
- syntax coloring for common Fortran keywords, declaration words, intrinsics,
  strings, comments, and numbers
- open/save support for Fortran source files
- checkboxes for `--trace-assign`, `--no-implicit-typing`, `--std=f2023`, and
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

With no file argument, `ofort` starts a REPL. Type Fortran source at the prompt
and use dot commands to run, edit, inspect, and save the current source buffer.

Common commands:

```text
.        run the current source and continue
.run     run; .run n repeats n times; use -- before program arguments
.runq    run and quit
.time    run and print elapsed-time statistics; .time n repeats n times
.quit    quit without running
.clear   clear the current source
.del     delete a line or range, such as .del 3, .del 2:4, .del :3, .del 4:
.ins     insert a source line before a line number
.rep     replace a source line
.rename  rename a variable token throughout the editable source
.list    list the current source
.decl    list declaration lines
.vars    list variable values
.info    list concise declaration-style variable information
.shapes  list array shapes
.sizes   list array sizes
.stats   list numeric array statistics
.load    load a file into the current source
.load-run load a file, run it once, and keep editing
```

The shortcuts `q` and `quit` also quit, unless `q` or `quit` has been defined
as a variable in the current source buffer. `.quit` always quits.

When `.load file.f90`, `.load-run file.f90`, `--load file.f90`, or
`--load-run file.f90` loads a complete program, the final `end` line is held
aside so new input is inserted before the end of the program. The held line is
restored when running or autosaving.

In interactive mode only, a bare expression line is evaluated immediately
against the current source buffer and prints its value. For example, after
entering `x = 3`, a line containing only `x` displays `3` immediately. Bare
expression lines are not added to the source buffer.

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
