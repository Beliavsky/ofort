# ofort

`ofort` is a small offline interpreter for a practical subset of Fortran.
It is written in C and runs Fortran source directly from the command line or
from an interactive REPL. The project began as an extraction from
[CodeBench](https://github.com/yu314-coder/CodeBench) by [yu314-coder](https://github.com/yu314-coder) and is now organized as a
standalone command-line interpreter.

`ofort` is intended for experimentation, small examples, tests, and interpreter
development. It is not a production Fortran compiler.

## Current Status

The interpreter currently supports a growing Fortran 90/95-style subset:

- scalar `INTEGER`, `REAL`, `DOUBLE PRECISION`, `COMPLEX`, `LOGICAL`, and
  `CHARACTER`
- arrays, array constructors, array sections, vector subscripts, allocatable
  arrays, allocatable scalars, and derived-type arrays
- modules, `use` imports, derived types, functions, subroutines, generic
  interfaces, optional arguments, `intent`, `pure` procedures, and elemental
  functions/subroutines
- `implicit none`, configurable implicit typing, declaration reordering in the
  REPL, assignment type checks, and diagnostics that include source lines
- `if`, `select case`, `do`, `do while`, labeled `do`, `exit`, `cycle`, `goto`,
  `forall`, `stop`, and `return`
- formatted `print`/`write`, `read`, `open`, `close`, `rewind`, internal I/O,
  simple external files, and simple unformatted stream I/O
- command-line arguments via `command_argument_count`, `get_command_argument`,
  and the nonstandard `getarg`

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

## Benchmarks

Benchmark helpers are in `scripts\bench_ofort.py` and the `benchmarks`
directory when present. The benchmark script can compare `ofort`, `ofort
--fast`, `gfortran`, `ifx`, and `lfortran`, depending on which tools are
installed.

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

## Test

```powershell
pytest -q
```

The test suite is intentionally small-program oriented. New language features
are usually added by creating a focused `tests/cases/x*.f90` source and a
matching `.out` file.
