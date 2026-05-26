#!/usr/bin/env python3
"""Interactive Python-to-Fortran runner backed by xp2f and ofort."""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFORT = ROOT / ("ofort.exe" if sys.platform.startswith("win") else "ofort")
DEFAULT_XP2F = Path(r"c:\python\Python-to-Fortran\xp2f.py")


@dataclass
class RunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    fortran: str = ""
    message: str = ""


def expression_display_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    leading = line[: len(line) - len(line.lstrip())]
    if leading:
        return line
    try:
        tree = ast.parse(line, mode="exec")
    except SyntaxError:
        return line
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
        return line
    expr = tree.body[0].value
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "print"
    ):
        return line
    try:
        text = ast.unparse(expr)
    except Exception:
        return line
    return f"{leading}print({text})"


def repl_source(lines: list[str]) -> str:
    return "\n".join(expression_display_line(line) for line in lines) + ("\n" if lines else "")


def is_setup_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    try:
        tree = ast.parse(line, mode="exec")
    except SyntaxError:
        return False
    return len(tree.body) == 1 and isinstance(tree.body[0], (ast.Import, ast.ImportFrom))


def session_has_executable_code(lines: list[str]) -> bool:
    for line in lines:
        if is_setup_only_line(line):
            continue
        return True
    return False


def run_session(
    lines: list[str],
    *,
    xp2f: Path,
    ofort: str,
    fast: bool,
    keep_fortran: Path | None = None,
) -> RunResult:
    source = repl_source(lines)
    with tempfile.TemporaryDirectory(prefix="opy_") as td:
        tmp = Path(td)
        py_path = tmp / "opy_session.py"
        f90_path = keep_fortran if keep_fortran is not None else tmp / "opy_session.f90"
        py_path.write_text(source, encoding="utf-8")

        xp2f_cmd = [sys.executable, str(xp2f), str(py_path), "--out", str(f90_path)]
        xp2f_run = subprocess.run(
            xp2f_cmd,
            cwd=str(xp2f.parent),
            text=True,
            capture_output=True,
        )
        if xp2f_run.returncode != 0:
            return RunResult(
                ok=False,
                stdout=xp2f_run.stdout,
                stderr=xp2f_run.stderr,
                message="translation failed",
            )

        try:
            fortran = f90_path.read_text(encoding="utf-8")
        except OSError:
            fortran = ""

        if "use python_mod" in fortran.lower():
            return RunResult(
                ok=False,
                fortran=fortran,
                message=(
                    "generated Fortran requires xp2f's python_mod helper; "
                    "current ofort cannot run that helper module directly"
                ),
            )

        ofort_cmd = [ofort]
        if fast:
            ofort_cmd.append("--fast")
        ofort_cmd.append(str(f90_path))
        ofort_run = subprocess.run(
            ofort_cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
        )
        return RunResult(
            ok=ofort_run.returncode == 0,
            stdout=ofort_run.stdout,
            stderr=ofort_run.stderr,
            fortran=fortran,
            message="" if ofort_run.returncode == 0 else f"ofort exited with code {ofort_run.returncode}",
        )


def print_incremental_output(previous: str, current: str) -> None:
    if current.startswith(previous):
        text = current[len(previous) :]
    else:
        text = current
    if text:
        print(text, end="" if text.endswith("\n") else "\n")


def run_file(args: argparse.Namespace) -> int:
    source = Path(args.source)
    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        print(f"opy: could not read {source}: {exc}", file=sys.stderr)
        return 1
    result = run_session(
        lines,
        xp2f=Path(args.xp2f),
        ofort=args.ofort,
        fast=not args.no_fast,
        keep_fortran=Path(args.out) if args.out else None,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if not result.ok:
        if result.message:
            print(f"opy: {result.message}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        return 1
    return 0


def run_repl(args: argparse.Namespace) -> int:
    print("opy interactive mode")
    print("Commands: fortran, list, clear, quit")
    lines: list[str] = []
    last_stdout = ""
    last_fortran = ""
    while True:
        try:
            line = input("opy> ")
        except EOFError:
            print()
            return 0
        line = line.lstrip("\ufeffï»¿")
        command = line.strip().lower()
        if command in {"quit", "exit"}:
            return 0
        if command == "clear":
            lines.clear()
            last_stdout = ""
            last_fortran = ""
            continue
        if command == "list":
            for i, saved in enumerate(lines, start=1):
                print(f"{i}: {saved}")
            continue
        if command == "fortran":
            if last_fortran:
                print(last_fortran, end="" if last_fortran.endswith("\n") else "\n")
            continue
        if not line.strip():
            continue
        if is_setup_only_line(line):
            lines.append(line)
            continue

        candidate = lines + [line]
        if not session_has_executable_code(candidate):
            lines = candidate
            continue
        result = run_session(
            candidate,
            xp2f=Path(args.xp2f),
            ofort=args.ofort,
            fast=not args.no_fast,
            keep_fortran=Path(args.out) if args.out else None,
        )
        if not result.ok:
            if result.message:
                print(f"opy: {result.message}")
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
            print("opy: line was not saved")
            continue

        lines = candidate
        last_fortran = result.fortran
        print_incremental_output(last_stdout, result.stdout)
        last_stdout = result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="interactive Python-to-Fortran runner using xp2f and ofort")
    parser.add_argument("source", nargs="?", help="optional Python source file; omitted starts the REPL")
    parser.add_argument("--xp2f", default=str(DEFAULT_XP2F), help=f"path to xp2f.py (default: {DEFAULT_XP2F})")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help=f"ofort command (default: {DEFAULT_OFORT})")
    parser.add_argument("--no-fast", action="store_true", help="run ofort without --fast")
    parser.add_argument("-o", "--out", help="write generated Fortran to this path")
    args = parser.parse_args()

    xp2f = Path(args.xp2f)
    if not xp2f.exists():
        print(f"opy: xp2f.py not found: {xp2f}", file=sys.stderr)
        return 1
    if args.source:
        return run_file(args)
    return run_repl(args)


if __name__ == "__main__":
    raise SystemExit(main())
