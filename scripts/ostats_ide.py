#!/usr/bin/env python3
"""Small IDE for translating R/statistics code to Fortran with xr2f.py."""

from __future__ import annotations

import argparse
import functools
import re
import shlex
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fortran_ide_base import (
    DOT_COMMAND_SUGGESTIONS,
    attach_text_search,
    clean_ofort_repl_diagnostics,
    fortran_for_repl_diagnostics,
)


DEFAULT_XR2F = Path(r"c:\python\fortran\xr2f.py")
DEFAULT_R_HELPER = DEFAULT_XR2F.with_name("r.f90")
ROOT = Path(__file__).resolve().parents[1]

COMPILER_MODES = [
    "ofort --fast",
    "ofort",
    "gfortran",
    "gfortran -O2",
    "gfortran -O3",
    "ifx",
    "ifx /O2",
    "lfortran",
]

R_FILETYPES = [("R files", "*.R *.r"), ("All files", "*.*")]
FORTRAN_FILETYPES = [("Fortran files", "*.f90 *.f95 *.f03 *.f08"), ("All files", "*.*")]

# Set this false to roll back the compact toolbar styling while keeping the
# descriptive control labels.
USE_SMALL_TOOLBAR_FONT = True
SMALL_TOOLBAR_FONT = ("TkDefaultFont", 8)

# Set this false to disable editor auto-completion of R braces/parentheses.
AUTO_COMPLETE_R_DELIMITERS = True

R_KEYWORDS = {
    "break",
    "else",
    "FALSE",
    "for",
    "function",
    "if",
    "Inf",
    "in",
    "NA",
    "NaN",
    "next",
    "NULL",
    "repeat",
    "return",
    "TRUE",
    "while",
}

FORTRAN_KEYWORDS = {
    "allocatable",
    "allocate",
    "call",
    "case",
    "contains",
    "cycle",
    "deallocate",
    "do",
    "elemental",
    "else",
    "end",
    "function",
    "if",
    "implicit",
    "impure",
    "integer",
    "interface",
    "intrinsic",
    "logical",
    "module",
    "none",
    "only",
    "parameter",
    "private",
    "program",
    "public",
    "pure",
    "real",
    "result",
    "return",
    "subroutine",
    "then",
    "type",
    "use",
}

R_BUILTINS = {
    "abs",
    "c",
    "cat",
    "cbind",
    "cor",
    "data.frame",
    "exp",
    "length",
    "log",
    "matrix",
    "max",
    "mean",
    "min",
    "print",
    "rbind",
    "rep",
    "sd",
    "seq",
    "sqrt",
    "sum",
    "var",
}


@dataclass
class TranslateResult:
    ok: bool
    fortran: str
    stdout: str
    stderr: str
    elapsed: float
    command: list[str]


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    elapsed: float
    command: list[str]


@dataclass
class LineProfileEntry:
    line: int
    count: int
    seconds: float
    source: str


def word_re(words: set[str]) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, words))) + r")\b")


R_KEYWORD_RE = word_re(R_KEYWORDS)
R_BUILTIN_RE = word_re(R_BUILTINS)
FORTRAN_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, FORTRAN_KEYWORDS))) + r")\b",
    re.IGNORECASE,
)
STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
NUMBER_RE = re.compile(r"\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b|\.\d+(?:[eE][+-]?\d+)?\b")
R_COMMENT_RE = re.compile(r"#[^\n]*")
FORTRAN_COMMENT_RE = re.compile(r"![^\n]*")
FUNC_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*(?=\()")
INCOMPLETE_R_TRAILING_RE = re.compile(r"(\^|\+|-|\*|/|%%|%/%|,|<-|=|\(|\[|\{)\s*$")
INCOMPLETE_R_BLOCK_HEADER_RE = re.compile(
    r"^\s*(?:for\s*\([^)]*\)|if\s*\([^)]*\)|while\s*\([^)]*\)|repeat|(?:[A-Za-z.]\w*\s*(?:<-|=)\s*)?function\s*\([^)]*\))\s*$"
)
FLOAT_TOKEN_PATTERN = re.compile(
    r"(?<![\w.])([+-]?(?:(?:\d+\.\d*|\.\d+)(?:[eEdD][+-]?\d+)?|\d+[eEdD][+-]?\d+))(?![\w.])"
)
LINE_PROFILE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+\.\d+)\s+(.*)$")
FORTRAN_PROC_START_RE = re.compile(
    r"^\s*(?:(?:pure|impure|elemental|recursive)\s+)*"
    r"(?:(?:real|integer|logical|complex|character|type|class)\b(?:\s*\([^)]*\))?\s*)?"
    r"(function|subroutine)\s+([A-Za-z_]\w*)\b",
    re.IGNORECASE,
)
HELPER_TAG = "helper_proc"


def display_fortran(fortran: str) -> str:
    return re.sub(
        r"\A! transpiled by xr2f\.py from .+? on .+?\n",
        "",
        fortran,
        count=1,
    )


def normalize_fortran_dp_alias(fortran: str) -> str:
    fortran = re.sub(
        r"use,\s*intrinsic\s*::\s*iso_fortran_env\s*,\s*only\s*:\s*real64\b",
        "use, intrinsic :: iso_fortran_env, only: dp => real64",
        fortran,
        flags=re.IGNORECASE,
    )
    fortran = re.sub(
        r"(?im)^[ \t]*integer\s*,\s*parameter\s*::\s*dp\s*=\s*real64\s*\r?\n",
        "",
        fortran,
    )
    return fortran


def format_float_tokens(text: str, decimals: int) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        try:
            value = float(token.replace("D", "E").replace("d", "e"))
        except ValueError:
            return token
        if "e" in token.lower() or "d" in token.lower():
            return f"{value:.{decimals}e}"
        return f"{value:.{decimals}f}"

    return FLOAT_TOKEN_PATTERN.sub(repl, text)


def r_source_waiting_for_completion(source: str, *, require_enter: bool = True) -> bool:
    if not source or source.endswith(("\n", "\r")):
        return False
    line = source.splitlines()[-1]
    code = R_COMMENT_RE.sub("", line).rstrip()
    if not code:
        return False
    if require_enter:
        return True
    if INCOMPLETE_R_TRAILING_RE.search(code):
        return True
    if INCOMPLETE_R_BLOCK_HEADER_RE.match(code):
        return True
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    quote = ""
    escape = False
    for ch in source:
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in {")", "]", "}"}:
            if stack and stack[-1] == ch:
                stack.pop()
    return bool(quote or stack)


def strip_r_comment(line: str) -> str:
    quote = ""
    escape = False
    for i, ch in enumerate(line):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def r_text_has_open_string(line: str) -> bool:
    quote = ""
    escape = False
    for ch in line:
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch == "#":
            break
    return bool(quote)


def r_line_opens_brace_block(line: str) -> bool:
    code = strip_r_comment(line).rstrip()
    return bool(code.endswith("{") and not r_text_has_open_string(line))


def leading_whitespace(text: str) -> str:
    return text[: len(text) - len(text.lstrip(" \t"))]


def next_nonblank_line(text: tk.Text) -> str:
    line_no = int(text.index("insert").split(".", 1)[0])
    last_line = int(text.index("end-1c").split(".", 1)[0])
    for candidate in range(line_no + 1, last_line + 1):
        line = text.get(f"{candidate}.0", f"{candidate}.end")
        if line.strip():
            return line
    return ""


def r_cursor_in_string_or_comment(text: tk.Text) -> bool:
    line = text.get("insert linestart", "insert")
    quote = ""
    escape = False
    for ch in line:
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch == "#":
            return True
    return bool(quote)


def selected_text_lines(widget: tk.Text) -> list[int]:
    try:
        start = widget.index("sel.first")
        end = widget.index("sel.last")
    except tk.TclError:
        return []
    start_line = int(start.split(".", 1)[0])
    end_line, end_col = (int(part) for part in end.split(".", 1))
    if end_col == 0 and end_line > start_line:
        end_line -= 1
    return list(range(start_line, end_line + 1))


def build_source_fortran_map(source_lines: list[str], fortran: str) -> dict[int, set[int]]:
    fortran_keys: dict[str, list[int]] = {}
    for line_no, line in enumerate(fortran.splitlines(), 1):
        for key in fortran_mapping_keys(line):
            fortran_keys.setdefault(key, []).append(line_no)

    mapping: dict[int, set[int]] = {}
    used_by_key: dict[str, int] = {}
    for source_no, line in enumerate(source_lines, 1):
        for key in r_mapping_keys(line):
            matches = fortran_keys.get(key, [])
            index = used_by_key.get(key, 0)
            if index < len(matches):
                mapping.setdefault(source_no, set()).add(matches[index])
                used_by_key[key] = index + 1
    return mapping


def r_mapping_keys(line: str) -> list[str]:
    code = R_COMMENT_RE.sub("", line).strip()
    if not code:
        return []
    keys: list[str] = []
    match = re.match(r"([A-Za-z.]\w*)\s*(?:<-|=(?!=))", code)
    if match:
        keys.append(f"assign:{r_name_to_fortran(match.group(1))}")
        if re.search(r"\bfunction\s*\(", code):
            keys.append(f"proc:{r_name_to_fortran(match.group(1))}")
        return keys
    match = re.match(r"for\s*\(\s*([A-Za-z.]\w*)\s+in\b", code)
    if match:
        return [f"do:{r_name_to_fortran(match.group(1))}"]
    if re.match(r"if\s*\(", code):
        return ["if"]
    if re.match(r"while\s*\(", code):
        return ["while"]
    if re.match(r"(?:print|cat)\s*\(", code):
        return ["print"]
    if code in {"break", "next", "return"}:
        return [{"break": "break", "next": "continue", "return": "return"}[code]]
    return ["print"]


def fortran_mapping_keys(line: str) -> list[str]:
    stripped = line.strip()
    lower = stripped.lower()
    if not stripped or lower.startswith(("!", "use ", "implicit ", "end ")):
        return []
    declaration_assignment = re.match(
        r"(?:real|integer|logical|character|complex)\b.*::\s*([A-Za-z_]\w*)\b\s*(?:\([^)]*\))?\s*=",
        lower,
    )
    if declaration_assignment:
        return [f"assign:{declaration_assignment.group(1).lower()}"]
    if lower.startswith(("real", "integer", "logical", "character", "complex")):
        return []
    match = re.match(r"([A-Za-z_]\w*)\s*=", lower)
    if match:
        return [f"assign:{match.group(1).lower()}"]
    match = re.match(r"do\s+([A-Za-z_]\w*)\s*=", lower)
    if match:
        return [f"do:{match.group(1).lower()}"]
    if lower.startswith("do while"):
        return ["while"]
    if lower.startswith("if ") or lower.startswith("if("):
        return ["if"]
    if lower.startswith(("print ", "write(", "call print_", "call disp")):
        return ["print"]
    match = re.match(
        r"(?:pure\s+)?(?:recursive\s+)?"
        r"(?:(?:real|integer|logical|character|complex)\b(?:\([^)]*\))?\s+)?"
        r"(?:function|subroutine)\s+([A-Za-z_]\w*)",
        lower,
    )
    if match:
        return [f"proc:{match.group(1).lower()}"]
    if lower.startswith("return"):
        return ["return"]
    if lower.startswith("exit"):
        return ["break"]
    if lower.startswith("cycle"):
        return ["continue"]
    return []


def r_name_to_fortran(name: str) -> str:
    return name.replace(".", "_").lower()


def read_text_normalized(path: Path) -> str:
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    return text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def translate_r_to_fortran(
    source: str,
    *,
    xr2f: Path,
    source_name: str = "ostats_session.R",
    timeout: float | None = 30.0,
) -> TranslateResult:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ostats_translate_") as tmp:
        tmpdir = Path(tmp)
        r_path = tmpdir / source_name
        f_path = tmpdir / "ostats_session.f90"
        r_path.write_text(source, encoding="utf-8")
        cmd = [sys.executable, str(xr2f), str(r_path), "--out", f_path.name, "--out-dir", str(tmpdir)]
        try:
            cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - start
            return TranslateResult(False, "", exc.stdout or "", f"xr2f timed out after {exc.timeout} seconds", elapsed, cmd)
        elapsed = time.perf_counter() - start
        fortran = f_path.read_text(encoding="utf-8", errors="replace") if f_path.exists() else ""
        if fortran:
            fortran = normalize_fortran_dp_alias(fortran)
        return TranslateResult(cp.returncode == 0 and bool(fortran), fortran, cp.stdout or "", cp.stderr or "", elapsed, cmd)


def run_r_source(
    source: str,
    *,
    rscript: str,
    source_name: str = "ostats_session.R",
    run_dir: Path = ROOT,
    timeout: float | None = 30.0,
) -> RunResult:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ostats_r_run_") as tmp:
        r_path = Path(tmp) / source_name
        r_path.write_text(source, encoding="utf-8")
        cmd = [*shlex.split(rscript), str(r_path)]
        try:
            cp = subprocess.run(cmd, cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            elapsed = time.perf_counter() - start
            return RunResult(False, "", f"{rscript!r} was not found on PATH", elapsed, cmd)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - start
            return RunResult(False, exc.stdout or "", f"R timed out after {exc.timeout} seconds", elapsed, cmd)
        elapsed = time.perf_counter() - start
        return RunResult(cp.returncode == 0, cp.stdout or "", cp.stderr or "", elapsed, cmd)


def helper_paths_for_fortran(fortran: str) -> list[Path]:
    helpers: list[Path] = []
    if re.search(r"(?im)^\s*use\s+r_mod\b", fortran) and DEFAULT_R_HELPER.exists():
        helpers.append(DEFAULT_R_HELPER)
    return helpers


@functools.lru_cache(maxsize=4)
def helper_procedure_definitions(path_text: str) -> dict[str, str]:
    path = Path(path_text)
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    definitions: dict[str, str] = {}
    i = 0
    while i < len(lines):
        match = FORTRAN_PROC_START_RE.match(lines[i])
        if not match:
            i += 1
            continue
        kind = match.group(1).lower()
        name = match.group(2)
        end_re = re.compile(rf"^\s*end\s+{kind}\s+{re.escape(name)}\b", re.IGNORECASE)
        start = i
        i += 1
        while i < len(lines):
            if end_re.match(lines[i]):
                i += 1
                definitions[name.lower()] = "\n".join(lines[start:i])
                break
            i += 1
        else:
            definitions[name.lower()] = "\n".join(lines[start:])
    return definitions


def r_helper_definitions() -> dict[str, str]:
    return helper_procedure_definitions(str(DEFAULT_R_HELPER))


def compiler_command(mode: str, sources: list[Path], exe: Path) -> list[str]:
    if mode == "gfortran":
        return ["gfortran", *map(str, sources), "-o", str(exe)]
    if mode == "gfortran -O2":
        return ["gfortran", "-O2", *map(str, sources), "-o", str(exe)]
    if mode == "gfortran -O3":
        return ["gfortran", "-O3", *map(str, sources), "-o", str(exe)]
    if mode == "ifx":
        return ifx_command(sources, exe, [])
    if mode == "ifx /O2":
        return ifx_command(sources, exe, ["/O2"] if sys.platform.startswith("win") else ["-O2"])
    if mode == "lfortran":
        return ["lfortran", *map(str, sources), "-o", str(exe)]
    return ["gfortran", *map(str, sources), "-o", str(exe)]


def ifx_command(sources: list[Path], exe: Path, options: list[str]) -> list[str]:
    if sys.platform.startswith("win"):
        return ["ifx", *options, *map(str, sources), f"/Fe:{exe}"]
    return ["ifx", *options, *map(str, sources), "-o", str(exe)]


def run_fortran_source(fortran: str, *, mode: str, run_dir: Path = ROOT, timeout: float = 30.0) -> RunResult:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ostats_f_run_") as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "ostats_session.f90"
        exe = tmpdir / ("ostats_session.exe" if sys.platform.startswith("win") else "ostats_session")
        source.write_text(fortran, encoding="utf-8")
        sources = [*helper_paths_for_fortran(fortran), source]
        if mode in {"ofort --fast", "ofort"}:
            cmd = ["ofort"]
            if mode == "ofort --fast":
                cmd.append("--fast")
            cmd.extend(str(path) for path in sources)
            try:
                cp = subprocess.run(cmd, cwd=run_dir, text=True, capture_output=True, timeout=timeout)
            except FileNotFoundError:
                elapsed = time.perf_counter() - start
                return RunResult(False, "", "ofort was not found on PATH", elapsed, cmd)
            except subprocess.TimeoutExpired as exc:
                elapsed = time.perf_counter() - start
                return RunResult(False, exc.stdout or "", f"ofort timed out after {exc.timeout} seconds", elapsed, cmd)
            elapsed = time.perf_counter() - start
            return RunResult(cp.returncode == 0, cp.stdout or "", cp.stderr or "", elapsed, cmd)

        compile_cmd = compiler_command(mode, sources, exe)
        try:
            cp = subprocess.run(compile_cmd, cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            elapsed = time.perf_counter() - start
            return RunResult(False, "", f"{compile_cmd[0]} was not found on PATH", elapsed, compile_cmd)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - start
            return RunResult(False, exc.stdout or "", f"{mode} compile timed out after {exc.timeout} seconds", elapsed, compile_cmd)
        if cp.returncode != 0:
            elapsed = time.perf_counter() - start
            return RunResult(False, cp.stdout or "", cp.stderr or "", elapsed, compile_cmd)
        run_cmd = [str(exe)]
        try:
            rp = subprocess.run(run_cmd, cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - start
            return RunResult(False, exc.stdout or "", f"{mode} run timed out after {exc.timeout} seconds", elapsed, run_cmd)
        elapsed = time.perf_counter() - start
        diagnostics = "\n".join(part.rstrip() for part in (cp.stdout, cp.stderr, rp.stderr) if part and part.strip())
        return RunResult(rp.returncode == 0, rp.stdout or "", diagnostics, elapsed, run_cmd)


def run_ofort_profile_lines(fortran: str, *, fast: bool, run_dir: Path = ROOT, timeout: float = 30.0) -> RunResult:
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ostats_profile_lines_") as tmp:
        source = Path(tmp) / "ostats_session.f90"
        source.write_text(fortran, encoding="utf-8")
        cmd = ["ofort"]
        if fast:
            cmd.append("--fast")
        cmd.append("--profile-lines")
        cmd.extend(str(path) for path in [*helper_paths_for_fortran(fortran), source])
        try:
            cp = subprocess.run(cmd, cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            elapsed = time.perf_counter() - start
            return RunResult(False, "", "ofort was not found on PATH", elapsed, cmd)
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - start
            return RunResult(False, exc.stdout or "", f"ofort timed out after {exc.timeout} seconds", elapsed, cmd)
        elapsed = time.perf_counter() - start
        return RunResult(cp.returncode == 0, cp.stdout or "", cp.stderr or "", elapsed, cmd)


def parse_line_profile(stderr: str) -> dict[int, LineProfileEntry]:
    if "line profile:" not in stderr:
        return {}
    profile_text = stderr.split("line profile:", 1)[1]
    entries: dict[int, LineProfileEntry] = {}
    for line in profile_text.splitlines():
        match = LINE_PROFILE_RE.match(line)
        if not match:
            continue
        line_no = int(match.group(1))
        entries[line_no] = LineProfileEntry(
            line=line_no,
            count=int(match.group(2)),
            seconds=float(match.group(3)),
            source=match.group(4),
        )
    return entries


def profile_stderr_without_table(stderr: str) -> str:
    if "line profile:" not in stderr:
        return stderr
    return stderr.split("line profile:", 1)[0].rstrip()


def annotate_fortran_with_line_profile(fortran: str, entries: dict[int, LineProfileEntry]) -> str:
    lines = fortran.splitlines()
    by_source: dict[str, list[LineProfileEntry]] = {}
    for entry in entries.values():
        by_source.setdefault(entry.source.strip(), []).append(entry)
    out: list[str] = []
    for line_no, line in enumerate(lines, 1):
        key = line.strip()
        entry = None
        matches = by_source.get(key)
        if matches:
            entry = matches.pop(0)
        if entry is None:
            entry = entries.get(line_no)
        if entry is None:
            out.append(line)
        else:
            out.append(f"{line}  ! count={entry.count} {entry.seconds:g} s")
    return "\n".join(out)


def make_scrollable_text(parent: tk.Widget, *, wrap: str = tk.NONE, undo: bool = False, height: int | None = None) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    options: dict[str, object] = {"wrap": wrap, "undo": undo}
    if height is not None:
        options["height"] = height
    text = tk.Text(frame, **options)
    yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
    xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
    text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    text.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    attach_text_search(text)
    return text


def apply_syntax(text: tk.Text) -> None:
    language = getattr(text, "syntax_language", "")
    content = text.get("1.0", "end-1c")
    for tag in ("keyword", "builtin", "string", "comment", "number", "function"):
        text.tag_remove(tag, "1.0", tk.END)
    if language == "r":
        apply_regex(text, R_KEYWORD_RE, "keyword", content)
        apply_regex(text, R_BUILTIN_RE, "builtin", content)
        apply_regex(text, FUNC_RE, "function", content, group=1)
        apply_regex(text, NUMBER_RE, "number", content)
        apply_regex(text, STRING_RE, "string", content)
        apply_regex(text, R_COMMENT_RE, "comment", content)
    elif language == "fortran":
        apply_regex(text, FORTRAN_KEYWORD_RE, "keyword", content)
        apply_regex(text, FUNC_RE, "function", content, group=1)
        apply_regex(text, NUMBER_RE, "number", content)
        apply_regex(text, STRING_RE, "string", content)
        apply_regex(text, FORTRAN_COMMENT_RE, "comment", content)


def apply_regex(text: tk.Text, pattern: re.Pattern[str], tag: str, content: str, *, group: int = 0) -> None:
    for match in pattern.finditer(content):
        start, end = match.span(group)
        if start != end:
            text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")


def configure_syntax(text: tk.Text) -> None:
    text.tag_configure("keyword", foreground="#0b5cad")
    text.tag_configure("builtin", foreground="#7b1f5c")
    text.tag_configure("function", foreground="#7b1f5c")
    text.tag_configure(HELPER_TAG, foreground="#005f73", underline=True)
    text.tag_configure("string", foreground="#8a4b08")
    text.tag_configure("comment", foreground="#4f7d36")
    text.tag_configure("number", foreground="#7a3db8")


class TextTooltip:
    def __init__(self, widget: tk.Text) -> None:
        self.widget = widget
        self.tip: tk.Toplevel | None = None
        self.current_text = ""

    def show(self, text: str, x: int, y: int) -> None:
        if self.tip is not None and text == self.current_text:
            self.tip.geometry(f"+{x + 14}+{y + 16}")
            return
        self.hide()
        self.current_text = text
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x + 14}+{y + 16}")
        label = ttk.Label(
            self.tip,
            text=text,
            justify=tk.LEFT,
            background="#fffdf0",
            relief=tk.SOLID,
            borderwidth=1,
            padding=(6, 4),
            font=("TkFixedFont", 9),
        )
        label.pack()

    def hide(self) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
        self.current_text = ""


class OstatsIde:
    def __init__(
        self,
        root: tk.Tk,
        *,
        xr2f: Path,
        rscript: str,
        compiler: str,
        source: Path | None,
    ) -> None:
        self.root = root
        self.xr2f = xr2f
        self.rscript = rscript
        self.compiler_var = tk.StringVar(value=compiler if compiler in COMPILER_MODES else "ofort --fast")
        self.status_var = tk.StringVar(value="Ready")
        self.elapsed_r_var = tk.StringVar(value="")
        self.elapsed_f_var = tk.StringVar(value="")
        self.timeout_var = tk.StringVar(value="30")
        self.output_decimals = tk.StringVar(value="")
        self.show_r_output = tk.BooleanVar(value=True)
        self.show_helper_hover = tk.BooleanVar(value=True)
        self.autocomplete_r = tk.BooleanVar(value=AUTO_COMPLETE_R_DELIMITERS)
        self.source_path: Path | None = None
        self.current_fortran = ""
        self.source_to_fortran_lines: dict[int, set[int]] = {}
        self.raw_r_output = ""
        self.raw_fortran_output = ""
        self.helper_tooltip: TextTooltip | None = None
        self.profile_annotated = False
        self.diagnostics_visible = False
        self.dot_suggestions_visible = False
        self.last_dot_command: str | None = None
        self.update_job: str | None = None
        self.highlight_job: str | None = None

        root.title("ostats IDE")
        root.geometry("1120x760")
        self.build_ui()
        if source is not None:
            self.load_source(source)
        else:
            self.set_text(
                self.r_text,
                "x <- c(1, 2, 3, 4)\n"
                "print(mean(x))\n"
                "print(sd(x))\n",
            )
            self.update_fortran()

    def build_ui(self) -> None:
        self.configure_toolbar_styles()
        button_style = "OstatsToolbar.TButton" if USE_SMALL_TOOLBAR_FONT else "TButton"
        label_style = "OstatsToolbar.TLabel" if USE_SMALL_TOOLBAR_FONT else "TLabel"
        check_style = "OstatsToolbar.TCheckbutton" if USE_SMALL_TOOLBAR_FONT else "TCheckbutton"
        combo_style = "OstatsToolbar.TCombobox" if USE_SMALL_TOOLBAR_FONT else "TCombobox"
        spin_style = "OstatsToolbar.TSpinbox" if USE_SMALL_TOOLBAR_FONT else "TSpinbox"
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        ttk.Button(toolbar, text="Open", command=self.open_source, style=button_style).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save R", command=self.save_source, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Save Fortran", command=self.save_fortran, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Translate", command=self.update_fortran, style=button_style).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Run R", command=self.run_r_current, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Run Fortran", command=self.run_fortran_current, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Run Both", command=self.run_both, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Clear All", command=self.clear_all, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Clear Output", command=self.clear_output, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(
            toolbar,
            text="Show R output",
            variable=self.show_r_output,
            command=self.update_output_layout,
            style=check_style,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(
            toolbar,
            text="Helper hover",
            variable=self.show_helper_hover,
            command=self.update_helper_hover_tags,
            style=check_style,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Help", command=self.show_help, style=button_style).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(toolbar, text="Compiler", style=label_style).pack(side=tk.LEFT, padx=(8, 3))
        ttk.Combobox(
            toolbar,
            textvariable=self.compiler_var,
            values=COMPILER_MODES,
            state="readonly",
            width=14,
            style=combo_style,
        ).pack(side=tk.LEFT)
        ttk.Label(toolbar, text="Timeout:", style=label_style).pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(
            toolbar,
            from_=0,
            to=999999,
            width=6,
            textvariable=self.timeout_var,
            style=spin_style,
        ).pack(side=tk.LEFT)

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        r_code_header = ttk.Frame(left)
        r_code_header.pack(fill=tk.X)
        ttk.Label(r_code_header, text="R input").pack(side=tk.LEFT)
        ttk.Checkbutton(
            r_code_header,
            text="Autocomplete",
            variable=self.autocomplete_r,
            style=check_style,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(r_code_header, text="Top", command=lambda: self.r_text.see("1.0")).pack(side=tk.RIGHT)
        ttk.Button(r_code_header, text="Bottom", command=lambda: self.r_text.see(tk.END)).pack(side=tk.RIGHT, padx=(0, 4))
        self.r_text = make_scrollable_text(left, undo=True)
        self.r_text.syntax_language = "r"
        configure_syntax(self.r_text)
        self.r_text.bind("<<Modified>>", self.source_modified)
        self.r_text.bind("<ButtonRelease-1>", self.source_selection_changed)
        self.r_text.bind("<KeyRelease>", self.source_selection_changed)
        self.r_text.bind("<Return>", self.r_return_event)
        self.r_text.bind("(", self.r_open_paren_event)
        self.r_text.bind("<KeyPress-quotedbl>", lambda event: self.r_quote_event(event, '"'))
        self.r_text.bind("<KeyPress-apostrophe>", lambda event: self.r_quote_event(event, "'"))

        fortran_code_header = ttk.Frame(right)
        fortran_code_header.pack(fill=tk.X)
        ttk.Label(fortran_code_header, text="Generated Fortran").pack(side=tk.LEFT)
        ttk.Label(fortran_code_header, textvariable=self.status_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(fortran_code_header, text="Hide Profile", command=self.clear_profile_annotations).pack(side=tk.RIGHT)
        ttk.Button(fortran_code_header, text="Profile Lines", command=self.profile_lines_current).pack(side=tk.RIGHT)
        ttk.Button(fortran_code_header, text="Top", command=lambda: self.fortran_text.see("1.0")).pack(side=tk.RIGHT)
        ttk.Button(fortran_code_header, text="Bottom", command=lambda: self.fortran_text.see(tk.END)).pack(side=tk.RIGHT, padx=(0, 4))
        self.fortran_text = make_scrollable_text(right)
        self.fortran_text.syntax_language = "fortran"
        configure_syntax(self.fortran_text)
        self.fortran_text.tag_configure("source_map_highlight", background="#fff3bf")
        self.helper_tooltip = TextTooltip(self.fortran_text)
        self.fortran_text.bind("<Motion>", self.fortran_motion)
        self.fortran_text.bind("<Leave>", lambda _event: self.hide_helper_tooltip())
        self.fortran_text.configure(state=tk.DISABLED)

        input_row = ttk.Frame(self.root)
        input_row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(input_row, text="ostats>").pack(side=tk.LEFT)
        self.entry = ttk.Entry(input_row)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.entry.bind("<Return>", self.submit_line_event)
        self.entry.bind("<KeyRelease>", self.entry_key_release)
        self.entry.bind("<Down>", self.dot_suggestion_down)
        self.entry.bind("<Up>", self.dot_suggestion_up)
        self.entry.bind("<Tab>", self.dot_suggestion_tab)
        self.entry.bind("<Escape>", self.hide_dot_suggestions_event)
        ttk.Button(input_row, text="Enter", command=self.submit_line).pack(side=tk.LEFT)
        self.dot_suggestion_list = tk.Listbox(self.root, height=5, exportselection=False)
        self.dot_suggestion_list.bind("<Double-Button-1>", self.dot_suggestion_double_click)
        self.dot_suggestion_list.bind("<Return>", self.dot_suggestion_return)

        self.output_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.output_pane.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=6, pady=(0, 6))
        self.r_output_frame = ttk.Frame(self.output_pane)
        self.fortran_output_frame = ttk.Frame(self.output_pane)
        self.diagnostics_frame = ttk.Frame(self.output_pane)

        r_header = ttk.Frame(self.r_output_frame)
        r_header.pack(fill=tk.X)
        ttk.Label(r_header, text="R Output").pack(side=tk.LEFT)
        ttk.Label(r_header, text="Decimals:").pack(side=tk.LEFT, padx=(12, 4))
        decimals = ttk.Spinbox(
            r_header,
            from_=0,
            to=16,
            width=4,
            textvariable=self.output_decimals,
            command=self.refresh_output_format,
        )
        decimals.pack(side=tk.LEFT)
        decimals.bind("<KeyRelease>", lambda _event: self.refresh_output_format())
        ttk.Label(r_header, textvariable=self.elapsed_r_var).pack(side=tk.RIGHT)
        self.r_output = make_scrollable_text(self.r_output_frame, wrap=tk.WORD, height=8)

        f_header = ttk.Frame(self.fortran_output_frame)
        f_header.pack(fill=tk.X)
        ttk.Label(f_header, text="Fortran Output").pack(side=tk.LEFT)
        ttk.Label(f_header, textvariable=self.elapsed_f_var).pack(side=tk.RIGHT)
        self.fortran_output = make_scrollable_text(self.fortran_output_frame, wrap=tk.WORD, height=8)

        d_header = ttk.Frame(self.diagnostics_frame)
        d_header.pack(fill=tk.X)
        ttk.Label(d_header, text="Diagnostics").pack(side=tk.LEFT)
        ttk.Button(d_header, text="Hide", command=self.hide_diagnostics).pack(side=tk.RIGHT)
        ttk.Button(d_header, text="Clear", command=self.clear_diagnostics).pack(side=tk.RIGHT, padx=(0, 4))
        self.diagnostics_text = make_scrollable_text(self.diagnostics_frame, wrap=tk.WORD, height=8)
        self.update_output_layout()

    def configure_toolbar_styles(self) -> None:
        if not USE_SMALL_TOOLBAR_FONT:
            return
        style = ttk.Style(self.root)
        style.configure("OstatsToolbar.TButton", font=SMALL_TOOLBAR_FONT)
        style.configure("OstatsToolbar.TLabel", font=SMALL_TOOLBAR_FONT)
        style.configure("OstatsToolbar.TCheckbutton", font=SMALL_TOOLBAR_FONT)
        style.configure("OstatsToolbar.TCombobox", font=SMALL_TOOLBAR_FONT)
        style.configure("OstatsToolbar.TSpinbox", font=SMALL_TOOLBAR_FONT)

    def source_modified(self, _event: tk.Event) -> None:
        if not self.r_text.edit_modified():
            return
        self.r_text.edit_modified(False)
        self.schedule_highlight()
        self.schedule_update()

    def submit_line_event(self, _event: tk.Event) -> str:
        self.submit_line()
        return "break"

    def submit_line(self) -> None:
        if self.dot_suggestions_visible and self.accept_dot_suggestion_if_partial():
            return
        line = self.entry.get()
        if not line.strip():
            return
        if line.strip().startswith("."):
            self.hide_dot_suggestions()
            self.entry.delete(0, tk.END)
            self.run_dot_command(line.strip())
            return
        self.entry.delete(0, tk.END)
        self.set_output(self.fortran_output, "Only dot commands are accepted in the ostats> line, for example .vars or .shapes")

    def entry_key_release(self, event: tk.Event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape", "Tab"}:
            return
        self.update_dot_suggestions()

    def update_dot_suggestions(self) -> None:
        text = self.entry.get().strip()
        if not text.startswith("."):
            self.hide_dot_suggestions()
            return
        matches = [cmd for cmd in DOT_COMMAND_SUGGESTIONS if cmd.startswith(text)]
        if not matches:
            self.hide_dot_suggestions()
            return
        self.dot_suggestion_list.delete(0, tk.END)
        for cmd in matches:
            self.dot_suggestion_list.insert(tk.END, cmd)
        self.dot_suggestion_list.selection_set(0)
        self.dot_suggestion_list.activate(0)
        if not self.dot_suggestions_visible:
            self.dot_suggestion_list.pack(side=tk.TOP, anchor=tk.W, padx=58, pady=(0, 4))
            self.dot_suggestions_visible = True

    def hide_dot_suggestions(self) -> None:
        if self.dot_suggestions_visible:
            self.dot_suggestion_list.pack_forget()
            self.dot_suggestions_visible = False

    def hide_dot_suggestions_event(self, _event: tk.Event) -> str:
        self.hide_dot_suggestions()
        return "break"

    def selected_dot_suggestion(self) -> str | None:
        if not self.dot_suggestions_visible:
            return None
        selection = self.dot_suggestion_list.curselection()
        if not selection:
            return None
        return str(self.dot_suggestion_list.get(selection[0]))

    def set_entry_to_dot_suggestion(self) -> bool:
        suggestion = self.selected_dot_suggestion()
        if suggestion is None:
            return False
        self.entry.delete(0, tk.END)
        self.entry.insert(0, suggestion)
        self.entry.icursor(tk.END)
        return True

    def accept_dot_suggestion_if_partial(self) -> bool:
        suggestion = self.selected_dot_suggestion()
        if suggestion is None:
            return False
        typed = self.entry.get().strip()
        if typed != suggestion:
            self.set_entry_to_dot_suggestion()
            self.hide_dot_suggestions()
            return True
        return False

    def dot_suggestion_tab(self, _event: tk.Event) -> str:
        if self.set_entry_to_dot_suggestion():
            self.hide_dot_suggestions()
        return "break"

    def dot_suggestion_return(self, _event: tk.Event) -> str:
        if self.set_entry_to_dot_suggestion():
            self.hide_dot_suggestions()
            self.submit_line()
        return "break"

    def dot_suggestion_double_click(self, _event: tk.Event) -> None:
        if self.set_entry_to_dot_suggestion():
            self.hide_dot_suggestions()
            self.entry.focus_set()

    def dot_suggestion_down(self, _event: tk.Event) -> str:
        if not self.dot_suggestions_visible:
            self.update_dot_suggestions()
            return "break"
        size = self.dot_suggestion_list.size()
        if size <= 0:
            return "break"
        selection = self.dot_suggestion_list.curselection()
        index = selection[0] if selection else 0
        index = min(index + 1, size - 1)
        self.dot_suggestion_list.selection_clear(0, tk.END)
        self.dot_suggestion_list.selection_set(index)
        self.dot_suggestion_list.activate(index)
        self.dot_suggestion_list.see(index)
        return "break"

    def dot_suggestion_up(self, _event: tk.Event) -> str:
        if not self.dot_suggestions_visible:
            return "break"
        selection = self.dot_suggestion_list.curselection()
        index = selection[0] if selection else 0
        index = max(index - 1, 0)
        self.dot_suggestion_list.selection_clear(0, tk.END)
        self.dot_suggestion_list.selection_set(index)
        self.dot_suggestion_list.activate(index)
        self.dot_suggestion_list.see(index)
        return "break"

    def r_autocomplete_enabled(self) -> bool:
        return AUTO_COMPLETE_R_DELIMITERS and self.autocomplete_r.get()

    def r_return_event(self, _event: tk.Event) -> str | None:
        if not self.r_autocomplete_enabled():
            return None
        line = self.r_text.get("insert linestart", "insert lineend")
        if not r_line_opens_brace_block(line):
            return None
        if next_nonblank_line(self.r_text).strip().startswith("}"):
            return None
        indent = leading_whitespace(line)
        inner = indent + "    "
        self.r_text.insert(tk.INSERT, "\n" + inner + "\n" + indent + "}")
        self.r_text.mark_set(tk.INSERT, "insert - 1 lines lineend")
        self.r_text.edit_modified(True)
        self.root.after_idle(self.source_modified, None)
        return "break"

    def r_open_paren_event(self, _event: tk.Event) -> str | None:
        if not self.r_autocomplete_enabled():
            return None
        if self.r_text.tag_ranges(tk.SEL):
            return None
        if r_cursor_in_string_or_comment(self.r_text):
            return None
        next_char = self.r_text.get("insert", "insert + 1c")
        if next_char == ")":
            return None
        self.r_text.insert(tk.INSERT, "()")
        self.r_text.mark_set(tk.INSERT, "insert - 1c")
        self.r_text.edit_modified(True)
        self.root.after_idle(self.source_modified, None)
        return "break"

    def r_quote_event(self, _event: tk.Event, quote: str) -> str | None:
        if not self.r_autocomplete_enabled():
            return None
        if self.r_text.tag_ranges(tk.SEL):
            return None
        if r_cursor_in_string_or_comment(self.r_text):
            return None
        previous_char = self.r_text.get("insert - 1c", "insert")
        next_char = self.r_text.get("insert", "insert + 1c")
        if previous_char == "\\" or next_char == quote:
            return None
        self.r_text.insert(tk.INSERT, quote + quote)
        self.r_text.mark_set(tk.INSERT, "insert - 1c")
        self.r_text.edit_modified(True)
        self.root.after_idle(self.source_modified, None)
        return "break"

    def schedule_highlight(self) -> None:
        if self.highlight_job is not None:
            self.root.after_cancel(self.highlight_job)
        self.highlight_job = self.root.after(120, lambda: apply_syntax(self.r_text))

    def schedule_update(self) -> None:
        if self.update_job is not None:
            self.root.after_cancel(self.update_job)
        self.update_job = self.root.after(400, lambda: self.update_fortran(auto=True))

    def source_text(self) -> str:
        return self.r_text.get("1.0", "end-1c")

    def timeout_seconds(self) -> float | None:
        raw = self.timeout_var.get().strip()
        try:
            value = float(raw)
        except ValueError:
            self.status_var.set("Invalid timeout; using 30s")
            return 30.0
        if value < 0:
            self.status_var.set("Invalid timeout; using 30s")
            return 30.0
        if value == 0:
            return None
        return value

    def update_fortran(self, *, auto: bool = False) -> None:
        source = self.source_text()
        if not source.strip():
            self.current_fortran = ""
            self.source_to_fortran_lines = {}
            self.set_fortran_text("")
            self.status_var.set("Ready")
            return
        if r_source_waiting_for_completion(source, require_enter=auto):
            self.status_var.set("Waiting for complete R statement")
            return
        result = translate_r_to_fortran(
            source,
            xr2f=self.xr2f,
            source_name=self.source_name(),
            timeout=self.timeout_seconds(),
        )
        if result.ok:
            self.current_fortran = result.fortran
            self.source_to_fortran_lines = build_source_fortran_map(source.splitlines(), display_fortran(result.fortran))
            self.set_fortran_text(result.fortran)
            self.status_var.set(f"Translated in {result.elapsed:.3f}s")
            self.set_output(self.fortran_output, "")
        else:
            self.source_to_fortran_lines = {}
            self.status_var.set(f"Translation failed in {result.elapsed:.3f}s")
            self.set_output(self.fortran_output, self.format_translate_error(result))

    def source_selection_changed(self, _event: tk.Event) -> None:
        self.root.after_idle(self.update_fortran_selection_highlight)

    def run_r_current(self) -> None:
        self.show_r_output.set(True)
        self.update_output_layout()
        result = run_r_source(
            self.source_text(),
            rscript=self.rscript,
            source_name=self.source_name(),
            run_dir=self.run_dir(),
            timeout=self.timeout_seconds(),
        )
        self.elapsed_r_var.set(f"{result.elapsed:.3f}s")
        self.set_output(self.r_output, self.format_run_output(result))

    def run_fortran_current(self) -> None:
        if not self.ensure_fortran():
            return
        result = run_fortran_source(
            self.current_fortran,
            mode=self.compiler_var.get(),
            run_dir=self.run_dir(),
            timeout=self.timeout_seconds(),
        )
        self.elapsed_f_var.set(f"{result.elapsed:.3f}s")
        self.set_output(self.fortran_output, self.format_run_output(result))
        self.refresh_diagnostics_watch()

    def profile_lines_current(self) -> None:
        if not self.ensure_fortran():
            return
        mode = self.compiler_var.get()
        if mode not in {"ofort --fast", "ofort"}:
            self.set_output(self.fortran_output, "Line profiling requires Run Fortran with: ofort or ofort --fast")
            return
        result = run_ofort_profile_lines(
            self.current_fortran,
            fast=(mode == "ofort --fast"),
            run_dir=self.run_dir(),
            timeout=self.timeout_seconds(),
        )
        self.elapsed_f_var.set(f"{result.elapsed:.3f}s")
        profile = parse_line_profile(result.stderr)
        diagnostics = profile_stderr_without_table(result.stderr)
        if result.ok and profile:
            self.show_profile_annotations(annotate_fortran_with_line_profile(display_fortran(self.current_fortran), profile))
            self.set_output(self.fortran_output, result.stdout.rstrip())
            if diagnostics.strip():
                self.set_output(self.fortran_output, "\n".join(part for part in (diagnostics, result.stdout.rstrip()) if part))
        else:
            self.clear_profile_annotations()
            self.set_output(
                self.fortran_output,
                self.format_run_output(RunResult(result.ok, result.stdout, diagnostics, result.elapsed, result.command)),
            )

    def run_both(self) -> None:
        self.show_r_output.set(True)
        self.update_output_layout()
        self.run_r_current()
        self.run_fortran_current()

    def run_dot_command(self, command: str, *, replace: bool = False) -> None:
        mode = self.compiler_var.get()
        self.diagnostics_visible = True
        self.update_output_layout()
        if mode not in {"ofort --fast", "ofort"}:
            self.append_diagnostics(f"ostats: dot commands require ofort; current compiler is {mode}\n")
            return
        if not self.ensure_fortran():
            self.append_diagnostics(f"ostats: cannot run {command}: no generated Fortran is available\n")
            return

        with tempfile.TemporaryDirectory(prefix="ostats_diag_") as td:
            source_path = Path(td) / "ostats_diagnostics.f90"
            helper_text = DEFAULT_R_HELPER.read_text(encoding="utf-8", errors="replace") if DEFAULT_R_HELPER.exists() else ""
            source_path.write_text(
                helper_text + "\n" + fortran_for_repl_diagnostics(self.current_fortran),
                encoding="utf-8",
            )
            cmd = ["ofort", "--nologo", "--repl"]
            if mode == "ofort --fast":
                cmd.append("--fast")
            cmd.extend(["--load-run", str(source_path)])
            try:
                run = subprocess.run(
                    cmd,
                    input=command + "\n.quit!\n",
                    cwd=str(self.run_dir()),
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds(),
                )
            except FileNotFoundError:
                self.append_diagnostics("ostats: ofort compiler not found\n")
                return
            except subprocess.TimeoutExpired as exc:
                self.append_diagnostics(f"ostats: dot command timed out after {exc.timeout} seconds\n")
                return

        text = clean_ofort_repl_diagnostics(run.stdout)
        if run.stderr:
            text += run.stderr
        if not text.strip() and run.returncode != 0:
            text = f"ofort exited with code {run.returncode}\n"
        self.last_dot_command = command
        if replace:
            self.set_text(self.diagnostics_text, "")
        self.append_diagnostics(f"ostats> {command}\n")
        if text:
            self.append_diagnostics(text if text.endswith("\n") else text + "\n")

    def refresh_diagnostics_watch(self) -> None:
        if self.diagnostics_visible and self.last_dot_command:
            self.run_dot_command(self.last_dot_command, replace=True)

    def ensure_fortran(self) -> bool:
        if self.current_fortran.strip():
            return True
        self.update_fortran()
        return bool(self.current_fortran.strip())

    def format_translate_error(self, result: TranslateResult) -> str:
        parts = [f"$ {' '.join(result.command)}"]
        if result.stdout.strip():
            parts.append(result.stdout.rstrip())
        if result.stderr.strip():
            parts.append(result.stderr.rstrip())
        return "\n".join(parts)

    def format_run_output(self, result: RunResult) -> str:
        if result.ok and not result.stderr.strip():
            return result.stdout.rstrip()
        parts: list[str] = []
        if not result.ok:
            parts.append(f"$ {' '.join(result.command)}")
        if result.stderr.strip():
            parts.append(result.stderr.rstrip())
        if result.stdout.strip():
            parts.append(result.stdout.rstrip())
        return "\n".join(parts)

    def source_name(self) -> str:
        return self.source_path.name if self.source_path is not None else "ostats_session.R"

    def run_dir(self) -> Path:
        return self.source_path.parent if self.source_path is not None else ROOT

    def set_fortran_text(self, text: str) -> None:
        self.profile_annotated = False
        self.fortran_text.configure(state=tk.NORMAL)
        self.set_text(self.fortran_text, display_fortran(text))
        self.fortran_text.configure(state=tk.DISABLED)
        apply_syntax(self.fortran_text)
        self.update_helper_hover_tags()
        self.update_fortran_selection_highlight()

    def update_fortran_selection_highlight(self) -> None:
        if not hasattr(self, "fortran_text"):
            return
        previous = str(self.fortran_text.cget("state"))
        self.fortran_text.configure(state=tk.NORMAL)
        self.fortran_text.tag_remove("source_map_highlight", "1.0", tk.END)
        if self.source_to_fortran_lines:
            for source_line in selected_text_lines(self.r_text):
                for fortran_line in sorted(self.source_to_fortran_lines.get(source_line, ())):
                    self.fortran_text.tag_add(
                        "source_map_highlight",
                        f"{fortran_line}.0",
                        f"{fortran_line}.end",
                    )
        self.fortran_text.tag_raise("source_map_highlight")
        self.fortran_text.configure(state=previous)

    def update_helper_hover_tags(self) -> None:
        self.hide_helper_tooltip()
        if not hasattr(self, "fortran_text"):
            return
        previous = str(self.fortran_text.cget("state"))
        self.fortran_text.configure(state=tk.NORMAL)
        self.fortran_text.tag_remove(HELPER_TAG, "1.0", tk.END)
        self.fortran_text.configure(state=previous)
        if self.show_helper_hover.get():
            self.tag_helper_procedures()

    def tag_helper_procedures(self) -> None:
        previous = str(self.fortran_text.cget("state"))
        self.fortran_text.configure(state=tk.NORMAL)
        self.fortran_text.tag_remove(HELPER_TAG, "1.0", tk.END)
        content = self.fortran_text.get("1.0", "end-1c")
        for name in r_helper_definitions():
            pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
            for match in pattern.finditer(content):
                self.fortran_text.tag_add(HELPER_TAG, f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        self.fortran_text.configure(state=previous)

    def fortran_motion(self, event: tk.Event) -> None:
        if not self.show_helper_hover.get():
            self.hide_helper_tooltip()
            return
        index = self.fortran_text.index(f"@{event.x},{event.y}")
        tags = self.fortran_text.tag_names(index)
        if HELPER_TAG not in tags:
            self.hide_helper_tooltip()
            return
        start = self.fortran_text.index(f"{index} wordstart")
        end = self.fortran_text.index(f"{index} wordend")
        name = self.fortran_text.get(start, end).lower()
        definition = r_helper_definitions().get(name)
        if definition and self.helper_tooltip is not None:
            self.helper_tooltip.show(definition, event.x_root, event.y_root)
        else:
            self.hide_helper_tooltip()

    def hide_helper_tooltip(self) -> None:
        if self.helper_tooltip is not None:
            self.helper_tooltip.hide()

    def set_text(self, text_widget: tk.Text, text: str) -> None:
        text_widget.delete("1.0", tk.END)
        if text:
            text_widget.insert("1.0", text)

    def append_diagnostics(self, text: str) -> None:
        self.diagnostics_text.configure(state=tk.NORMAL)
        self.diagnostics_text.insert(tk.END, text)
        self.diagnostics_text.see(tk.END)

    def set_readonly_text(self, text_widget: tk.Text, text: str) -> None:
        previous = str(text_widget.cget("state"))
        text_widget.configure(state=tk.NORMAL)
        self.set_text(text_widget, text)
        text_widget.configure(state=previous)

    def show_profile_annotations(self, text: str) -> None:
        self.profile_annotated = True
        previous = str(self.fortran_text.cget("state"))
        self.fortran_text.configure(state=tk.NORMAL)
        self.set_text(self.fortran_text, text)
        self.fortran_text.configure(state=previous)
        apply_syntax(self.fortran_text)
        self.update_helper_hover_tags()
        self.update_fortran_selection_highlight()

    def clear_profile_annotations(self) -> None:
        if not self.profile_annotated:
            return
        self.profile_annotated = False
        previous = str(self.fortran_text.cget("state"))
        self.fortran_text.configure(state=tk.NORMAL)
        self.set_text(self.fortran_text, display_fortran(self.current_fortran))
        self.fortran_text.configure(state=previous)
        apply_syntax(self.fortran_text)
        self.update_helper_hover_tags()
        self.update_fortran_selection_highlight()

    def set_output(self, text_widget: tk.Text, text: str) -> None:
        if hasattr(self, "r_output") and text_widget is self.r_output:
            self.raw_r_output = text
        elif hasattr(self, "fortran_output") and text_widget is self.fortran_output:
            self.raw_fortran_output = text
        self.write_output_display(text_widget, text)

    def write_output_display(self, text_widget: tk.Text, text: str) -> None:
        text_widget.delete("1.0", tk.END)
        text = self.format_output_text(text)
        if text:
            text_widget.insert("1.0", text + ("\n" if not text.endswith("\n") else ""))

    def format_output_text(self, text: str) -> str:
        raw = self.output_decimals.get().strip()
        if not raw:
            return text
        try:
            decimals = int(raw)
        except ValueError:
            return text
        if decimals < 0:
            return text
        return format_float_tokens(text, decimals)

    def refresh_output_format(self) -> None:
        self.write_output_display(self.r_output, self.raw_r_output)
        self.write_output_display(self.fortran_output, self.raw_fortran_output)

    def clear_output(self) -> None:
        self.set_output(self.r_output, "")
        self.set_output(self.fortran_output, "")
        self.elapsed_r_var.set("")
        self.elapsed_f_var.set("")

    def clear_diagnostics(self) -> None:
        self.set_text(self.diagnostics_text, "")
        self.last_dot_command = None

    def hide_diagnostics(self) -> None:
        self.diagnostics_visible = False
        self.update_output_layout()

    def update_output_layout(self) -> None:
        if not hasattr(self, "output_pane"):
            return
        panes = set(self.output_pane.panes())
        r_name = str(self.r_output_frame)
        fortran_name = str(self.fortran_output_frame)
        diagnostics_name = str(self.diagnostics_frame)
        if r_name in panes:
            self.output_pane.forget(self.r_output_frame)
        if fortran_name in panes:
            self.output_pane.forget(self.fortran_output_frame)
        if diagnostics_name in panes:
            self.output_pane.forget(self.diagnostics_frame)
        if self.show_r_output.get():
            self.output_pane.add(self.r_output_frame, weight=1)
            self.output_pane.add(self.fortran_output_frame, weight=1)
        else:
            self.output_pane.add(self.fortran_output_frame, weight=1)
        if self.diagnostics_visible:
            self.output_pane.add(self.diagnostics_frame, weight=1)

    def clear_all(self) -> None:
        if self.update_job is not None:
            self.root.after_cancel(self.update_job)
            self.update_job = None
        if self.highlight_job is not None:
            self.root.after_cancel(self.highlight_job)
            self.highlight_job = None
        self.source_path = None
        self.current_fortran = ""
        self.source_to_fortran_lines = {}
        self.set_text(self.r_text, "")
        self.r_text.edit_modified(False)
        self.set_fortran_text("")
        self.clear_output()
        self.clear_diagnostics()
        self.diagnostics_visible = False
        self.show_r_output.set(True)
        self.update_output_layout()
        self.status_var.set("Ready")
        self.root.title("ostats IDE")

    def open_source(self) -> None:
        path = filedialog.askopenfilename(title="Open R source", filetypes=R_FILETYPES)
        if path:
            self.load_source(Path(path))

    def load_source(self, path: Path) -> None:
        self.source_path = path
        self.set_text(self.r_text, read_text_normalized(path))
        self.r_text.edit_modified(False)
        self.root.title(f"ostats IDE - {path}")
        apply_syntax(self.r_text)
        self.update_fortran()

    def save_source(self) -> None:
        path = self.source_path
        if path is None:
            selected = filedialog.asksaveasfilename(title="Save R source", filetypes=R_FILETYPES, defaultextension=".R")
            if not selected:
                return
            path = Path(selected)
            self.source_path = path
        path.write_text(self.source_text(), encoding="utf-8")
        self.status_var.set(f"Saved {path}")

    def save_fortran(self) -> None:
        if not self.current_fortran.strip():
            self.update_fortran()
        if not self.current_fortran.strip():
            return
        initial = self.source_path.with_suffix(".f90").name if self.source_path is not None else "ostats_session.f90"
        selected = filedialog.asksaveasfilename(
            title="Save Fortran source",
            filetypes=FORTRAN_FILETYPES,
            defaultextension=".f90",
            initialfile=initial,
        )
        if not selected:
            return
        Path(selected).write_text(self.current_fortran, encoding="utf-8")
        self.status_var.set(f"Saved {selected}")

    def show_help(self) -> None:
        messagebox.showinfo(
            "ostats IDE Help",
            "Write R code in the left pane. xr2f.py generates Fortran in the right pane.\n\n"
            "Run R executes the original R code with Rscript. Run Fortran runs the generated "
            "Fortran with the selected backend. Run Both fills both output panes.\n\n"
            "Successful runs show only program output. Warnings and errors are shown when present.",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open an R-to-Fortran IDE using xr2f.py.")
    parser.add_argument("source_file", nargs="?", help="optional R source file to open")
    parser.add_argument("--source", help="R source file to open; overrides positional source")
    parser.add_argument("--xr2f", default=str(DEFAULT_XR2F), help="path to xr2f.py")
    parser.add_argument("--rscript", default="Rscript", help="Rscript command")
    parser.add_argument("--compiler", choices=COMPILER_MODES, default="ofort --fast", help="initial Fortran backend")
    args = parser.parse_args(argv)

    source_arg = args.source or args.source_file
    source = Path(source_arg) if source_arg else None
    if source is not None and not source.exists():
        print(f"ostats IDE: source file not found: {source}", file=sys.stderr)
        return 2
    xr2f = Path(args.xr2f)
    if not xr2f.exists():
        print(f"ostats IDE: xr2f.py not found: {xr2f}", file=sys.stderr)
        return 2

    root = tk.Tk()
    OstatsIde(root, xr2f=xr2f, rscript=args.rscript, compiler=args.compiler, source=source)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
