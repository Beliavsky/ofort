# ofort

`ofort` is a small tree-walking interpreter for a subset of Fortran 90/95/2003.
It is extracted from the [CodeBench](https://github.com/yu314-coder/CodeBench) project of [yu314-coder](https://github.com/yu314-coder) into a standalone C command-line
project.

`REAL` and `DOUBLE PRECISION` are distinguished by type tag/kind, but both are
currently stored using C `double` internally.

## Current support

`ofort` is intended for experimenting with small programs, examples, and
interpreter development. It is not a full Fortran compiler.

Implemented pieces include scalar `INTEGER`, `REAL`, `DOUBLE PRECISION`,
`CHARACTER`, `LOGICAL`, arrays and allocatable arrays, `implicit none` checking,
assignment type checks, `if`, `do`, labeled `do`, `exit`, subroutines, basic
functions, internal and external formatted I/O, simple unformatted stream I/O,
and interactive expression evaluation.

Supported intrinsics include common numeric, conversion, character, array, and
random-number routines such as `abs`, `sqrt`, `sin`, `cos`, `exp`, `log`, `mod`,
`modulo`, `dim`, `aint`, `nint`, `int`, `real`, `dble`, `dprod`, `kind`, `len`,
`trim`, `sum`, `product`, `maxval`, `minval`, `allocated`, `lbound`, `ubound`,
`random_number`, `random_seed`, and `system_clock`.

Known missing Fortran 95 intrinsics and candidates for future work are tracked
in `intrinsics_to_do.txt`.

## Build

```powershell
make
```

Alternative compiler targets:

```powershell
make gcc
make clang
```

## Run

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

By default, undeclared variables are rejected. To enable historical implicit
typing, where names beginning with I-N are integers and other names are real,
use:

```powershell
.\ofort.exe --implicit-typing x.f90
```

To start an interactive session with an existing file loaded into the edit
buffer:

```powershell
.\ofort.exe --load x.f90
```

To load a file, run it once, and stay in the interactive session:

```powershell
.\ofort.exe --load-run x.f90
```

To compare `ofort` output with `gfortran` for a program:

```powershell
.\ofort.exe --check-gfortran x.f90
```

To lex and parse a program without running it:

```powershell
.\ofort.exe --check x.f90
```

To run `ofort` on every file matched by a glob:

```powershell
python .\scripts\xofort.py "tests\cases\*.f90"
python .\scripts\xofort.py --check "tests\cases\*.f90"
python .\scripts\xofort.py --limit 5 "tests\cases\*.f90"
python .\scripts\xofort.py --timeout 30 "tests\cases\*.f90"
python .\scripts\xofort.py --max-lines 100 "tests\cases\*.f90"
python .\scripts\xofort.py --quiet "tests\cases\*.f90"
python .\scripts\xofort.py --filter "gfortran -c -std=f95" "tests\cases\*.f90"
```

The batch runner prints each file name and line count before processing it,
uses a 30-second per-file timeout by default, and reports elapsed time at the
end. `--quiet` suppresses output for files that `ofort` handles successfully.
`--filter` runs the given command with the source file appended and skips files
for which that command fails.

With no file argument, `ofort` starts an interactive session. Type source at the
prompt and use these commands:

```text
.       run the current source and continue
.run    run the current source; .run n repeats n times; use -- before program arguments
.runq   run the current source and quit; accepts the same count and arguments as .run
.time   run the current source and print elapsed-time statistics; .time n repeats n times
.quit   quit without running
.clear  clear the current source
.del    delete a source line or range, such as .del 3, .del 2:4, .del :3, or .del 4:
.ins    insert a source line before a line number, such as .ins 3 integer :: j
.rep    replace a source line, such as .rep 5 print *, i, j
.rename rename a variable token throughout the editable source, such as .rename i j
.list   list the current source
.decl   list declaration lines from the current source
.vars   list current variable values, or selected names such as .vars i x
.info   list declaration-style variable details, or selected names such as .info i x
.shapes list array shapes, or selected names such as .shapes x y
.sizes  list array sizes, or selected names such as .sizes x y
.stats  list numeric array statistics, or selected names such as .stats x y
.load   load a file into the current source
.load-run load a file, run it once, and keep editing
```

For repeated runs, command arguments can be supplied after `--`, for example
`.run 3 -- alpha beta`.

When `.load file.f90`, `.load-run file.f90`, `--load file.f90`, or
`--load-run file.f90` loads a complete program, a final `end...` line is
temporarily held aside so new input is inserted before the end of the program.
The held line is restored when running or autosaving.

The shortcuts `q` and `quit` also quit, unless `q` or `quit` has been defined
as a variable in the current source buffer. `.quit` always quits.

When an interactive session exits with a non-empty source buffer, the buffer is
saved automatically as `main.f90`, or `main1.f90`, `main2.f90`, and so on if
earlier names already exist.

In interactive mode only, a bare expression line is evaluated immediately
against the current source buffer and prints its value. For example, after
entering `x = 3`, a line containing only `x` displays `3` immediately. Bare
expression lines are not added to the source buffer.

## Test

```powershell
pytest -q
```
