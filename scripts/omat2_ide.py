#!/usr/bin/env python3
"""Worksheet-style omat IDE using the shared Fortran translator IDE shell."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import tkinter as tk

from fortran_ide_base import (
    DEFAULT_COMPILER_MODES,
    FortranTranslatorIde,
    IdeResult,
)
from omat import DEFAULT_OFORT, OmatError, line_closes_block, line_opens_block, translate_source


OMAT2_HELP_TEXT = """\
omat IDE

Workflow
Write Octave code in the left pane. Generated Fortran appears in the right pane.
Use Run Octave, Run Fortran, or Run Both to compare behavior.

Fortran Mode
ofort-optimized mode may use ofort-specific modules for speed. Generic mode
emits portable helper procedures where possible.

Compilers
The default Fortran backend is ofort --fast. The compiler selector can also run
ofort, gfortran, ifx, or lfortran when they are installed.

Limits
omat supports a numerical Octave-like subset, not the full Octave language.
"""


class OmatAdapter:
    name = "omat"
    source_label = "Octave"
    prompt = "omat>"
    default_extension = ".m"
    filetypes = [("Octave files", "*.m"), ("All files", "*.*")]
    help_text = OMAT2_HELP_TEXT
    source_syntax = "octave"
    fortran_syntax = "fortran"

    def __init__(self, octave: str = "octave") -> None:
        self.octave = octave

    def translate(
        self,
        source: str,
        *,
        generic: bool,
        explain_helpers: bool,
        source_path: Path | None = None,
    ) -> IdeResult:
        del explain_helpers
        try:
            fortran = translate_source(source, generic=generic, source_path=source_path)
        except OmatError as exc:
            return IdeResult(ok=False, message=str(exc))
        return IdeResult(ok=True, fortran=fortran)

    def run_source(self, source: str, *, source_path: Path | None = None) -> IdeResult:
        octave = shutil.which(self.octave)
        if octave is None:
            return IdeResult(ok=False, message=f"{self.octave} not found")
        if source_path is not None:
            run = subprocess.run(
                [octave, "--quiet", str(source_path)],
                cwd=source_path.parent,
                text=True,
                capture_output=True,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="omat2_") as td:
                path = Path(td) / "omat_source.m"
                path.write_text(source, encoding="utf-8")
                run = subprocess.run(
                    [octave, "--quiet", str(path)],
                    cwd=td,
                    text=True,
                    capture_output=True,
                )
        return IdeResult(
            ok=run.returncode == 0,
            stdout=run.stdout,
            stderr=run.stderr,
            message="" if run.returncode == 0 else f"Octave exited with code {run.returncode}",
        )

    def is_incomplete_source(self, source: str) -> bool:
        return source_block_depth(source) != 0 or bracket_validation_error(source) is not None

    def next_line_indent(self, line: str) -> str:
        base = re.match(r"[ \t]*", line).group(0)
        if line_opens_block(line.strip()):
            return base + "    "
        return base


def source_block_depth(source: str) -> int:
    depth = 0
    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line_closes_block(line) and depth > 0:
            depth -= 1
        elif line_opens_block(line):
            depth += 1
    return depth


def bracket_validation_error(source: str) -> str | None:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closers = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int, int]] = []
    in_single = False
    in_double = False
    for line_no, line in enumerate(source.splitlines(), start=1):
        i = 0
        while i < len(line):
            ch = line[i]
            if in_single:
                if ch == "'":
                    if i + 1 < len(line) and line[i + 1] == "'":
                        i += 2
                        continue
                    in_single = False
                i += 1
                continue
            if in_double:
                if ch == '"':
                    if i + 1 < len(line) and line[i + 1] == '"':
                        i += 2
                        continue
                    in_double = False
                i += 1
                continue
            if ch == "%":
                break
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch in pairs:
                stack.append((ch, line_no, i + 1))
            elif ch in closers:
                if not stack or stack[-1][0] != closers[ch]:
                    return f"unmatched '{ch}' at line {line_no}, column {i + 1}"
                stack.pop()
            i += 1
    if in_single:
        return "unterminated single-quoted string"
    if in_double:
        return "unterminated double-quoted string"
    if stack:
        ch, line_no, col = stack[-1]
        return f"unmatched '{ch}' opened at line {line_no}, column {col}"
    return None


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worksheet-style GUI for omat using the shared IDE shell.")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help="ofort command")
    parser.add_argument("--octave", default="octave", help="Octave command")
    parser.add_argument("--compiler", choices=DEFAULT_COMPILER_MODES, help="initial compiler dropdown selection")
    parser.add_argument("--generic", action="store_true", help="start in generic Fortran mode")
    parser.add_argument("--no-immediate", action="store_true", help="start with immediate run disabled")
    parser.add_argument("--source", type=Path, help="open this Octave source at startup")
    parser.add_argument("--session", type=Path, help="open this saved IDE session at startup")
    parser.add_argument("source_file", nargs="?", type=Path, help="open this Octave source at startup")
    args = parser.parse_args(argv)

    root = tk.Tk()
    ide = FortranTranslatorIde(
        root,
        adapter=OmatAdapter(octave=args.octave),
        ofort=args.ofort,
        compiler=args.compiler,
        immediate=not args.no_immediate,
        source=args.source or args.source_file,
        session=args.session,
    )
    if args.generic:
        ide.fortran_mode.set("generic")
        ide.regenerate_fortran()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
