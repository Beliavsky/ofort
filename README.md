# ofort

`ofort` is a small tree-walking interpreter for a subset of Fortran 90/95/2003.
It is extracted from the [CodeBench](https://github.com/yu314-coder/CodeBench) project of [yu314-coder](https://github.com/yu314-coder) into a standalone C command-line
project.

`REAL` and `DOUBLE PRECISION` are distinguished by type tag/kind, but both are
currently stored using C `double` internally.

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

With no file argument, type source at the prompt and enter a single `.` line to
execute.

## Test

```powershell
pytest -q
```
