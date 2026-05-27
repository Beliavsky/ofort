#!/usr/bin/env python3
"""Small worksheet-style IDE for opy."""

from __future__ import annotations

import argparse
import ast
import codeop
import re
import subprocess
import sys
import time
import tkinter as tk
import tempfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from opy import (
    DEFAULT_OFORT,
    DEFAULT_XP2F,
    RunResult,
    incremental_output_text,
    is_setup_only_line,
    run_session,
    session_has_executable_code,
    translate_session,
)


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


class OpyIde:
    def __init__(
        self,
        root: tk.Tk,
        *,
        xp2f: str,
        ofort: str,
        fast: bool = True,
        compiler: str | None = None,
        immediate: bool = False,
    ) -> None:
        self.root = root
        self.xp2f = Path(xp2f)
        self.ofort = ofort
        initial_compiler = compiler if compiler in COMPILER_MODES else ("ofort --fast" if fast else "ofort")
        self.compiler_var = tk.StringVar(value=initial_compiler)
        self.immediate = tk.BooleanVar(value=immediate)
        self.update_job: str | None = None
        self.highlight_job: str | None = None
        self.current_fortran = ""
        self.current_valid = False
        self.last_diagnostic = ""
        self.last_source_text = ""
        self.committed_source_text = ""
        self.last_stdout = ""
        self.elapsed_var = tk.StringVar(value="")
        self.source_path: Path | None = None

        root.title("opy IDE")
        root.geometry("1100x750")
        self.build_ui()
        self.update_fortran()

    def build_ui(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)

        ttk.Button(toolbar, text="Open", command=self.open_source).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save Python", command=self.save_source).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Save Fortran", command=self.save_fortran).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Run", command=self.run_current).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(toolbar, text="Run with:").pack(side=tk.LEFT, padx=(12, 4))
        compiler_box = ttk.Combobox(
            toolbar,
            textvariable=self.compiler_var,
            values=COMPILER_MODES,
            width=14,
            state="readonly",
        )
        compiler_box.pack(side=tk.LEFT)
        ttk.Checkbutton(toolbar, text="Immediate run", variable=self.immediate).pack(side=tk.LEFT, padx=(12, 0))

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        ttk.Label(left, text="Python input").pack(anchor=tk.W)
        self.source_text = tk.Text(left, wrap=tk.NONE, undo=True)
        self.source_text.syntax_language = "python"
        self.source_text.pack(fill=tk.BOTH, expand=True)
        self.source_text.bind("<<Modified>>", self.source_modified)
        self.source_text.bind("<Return>", self.source_return_event)
        configure_syntax_tags(self.source_text)

        fortran_header = ttk.Frame(right)
        fortran_header.pack(fill=tk.X)
        ttk.Label(fortran_header, text="Generated Fortran").pack(side=tk.LEFT)
        ttk.Button(fortran_header, text="Top", command=self.scroll_fortran_top).pack(side=tk.RIGHT)
        ttk.Button(fortran_header, text="Bottom", command=self.scroll_fortran_bottom).pack(side=tk.RIGHT, padx=(0, 4))
        self.fortran_text = tk.Text(right, wrap=tk.NONE, undo=False)
        self.fortran_text.syntax_language = "fortran"
        self.fortran_text.pack(fill=tk.BOTH, expand=True)
        self.fortran_text.configure(state=tk.DISABLED)
        configure_syntax_tags(self.fortran_text)

        input_row = ttk.Frame(self.root)
        input_row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(input_row, text="opy>").pack(side=tk.LEFT)
        self.entry = ttk.Entry(input_row)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.entry.bind("<Return>", self.submit_line_event)
        ttk.Button(input_row, text="Enter", command=self.submit_line).pack(side=tk.LEFT)

        output_row = ttk.Frame(self.root)
        output_row.pack(side=tk.TOP, fill=tk.X, padx=6)
        ttk.Label(output_row, text="Output").pack(side=tk.LEFT)
        ttk.Label(output_row, textvariable=self.elapsed_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(output_row, text="Clear Output", command=self.clear_output).pack(side=tk.RIGHT)
        self.output_text = tk.Text(self.root, height=10, wrap=tk.WORD, undo=False)
        self.output_text.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=6, pady=(0, 6))
        self.entry.focus_set()

    def submit_line_event(self, _event: tk.Event) -> str:
        self.submit_line()
        return "break"

    def submit_line(self) -> None:
        line = self.entry.get()
        if not line.strip():
            return
        text = self.source_text.get("1.0", "end-1c")
        if text and not text.endswith("\n"):
            line = "\n" + line
        self.source_text.insert(tk.END, line + "\n")
        self.source_text.see(tk.END)
        self.entry.delete(0, tk.END)
        self.commit_source_change()

    def source_modified(self, _event: tk.Event) -> None:
        if not self.source_text.edit_modified():
            return
        self.source_text.edit_modified(False)
        self.schedule_source_highlight()
        source = self.source_text.get("1.0", "end-1c")
        if not source.strip():
            self.current_fortran = ""
            self.current_valid = False
            self.last_diagnostic = ""
            self.last_source_text = ""
            self.committed_source_text = ""
            self.last_stdout = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
        elif not source.startswith(self.last_source_text):
            self.last_stdout = ""

    def source_return_event(self, _event: tk.Event) -> None:
        line = self.source_text.get("insert linestart", "insert lineend")
        indent = next_line_indent(line)
        self.source_text.insert(tk.INSERT, "\n" + indent)
        self.root.after_idle(self.commit_source_change)
        return "break"

    def commit_source_change(self) -> None:
        source = self.source_text.get("1.0", "end-1c")
        self.committed_source_text = source
        self.schedule_update_fortran(source)
        if self.immediate.get() and source.startswith(self.last_source_text):
            appended = source[len(self.last_source_text):]
            if immediate_run_append(appended):
                self.root.after(
                    350,
                    lambda source=source: self.run_current(
                        incremental=True,
                        source_override=source,
                    ),
                )
        elif not source.startswith(self.last_source_text):
            self.last_stdout = ""
        self.last_source_text = source

    def schedule_update_fortran(self, source: str | None = None) -> None:
        if self.update_job is not None:
            self.root.after_cancel(self.update_job)
        self.update_job = self.root.after(300, lambda: self.update_fortran(source))

    def schedule_source_highlight(self) -> None:
        if self.highlight_job is not None:
            self.root.after_cancel(self.highlight_job)
        self.highlight_job = self.root.after(120, self.highlight_source)

    def highlight_source(self) -> None:
        self.highlight_job = None
        apply_syntax_highlighting(self.source_text)

    def update_fortran(self, source_override: str | None = None) -> None:
        self.update_job = None
        source = source_override
        if source is None:
            source = self.source_text.get("1.0", "end-1c")
        if not source.strip():
            self.current_fortran = ""
            self.current_valid = False
            self.last_diagnostic = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
            return
        if is_incomplete_python_source(source):
            self.current_valid = False
            self.last_diagnostic = ""
            preview = partial_fortran_preview(source)
            self.set_text(self.fortran_text, preview, scroll_to_end=True)
            return
        lines = source.splitlines()
        if not session_has_executable_code(lines):
            self.current_fortran = ""
            self.current_valid = True
            self.last_diagnostic = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
            return
        result = self.translate_and_run(source.splitlines(), run=False)
        if not result.ok:
            self.invalidate_current_source(result)
            return
        self.current_fortran = result.fortran
        self.current_valid = True
        self.last_diagnostic = ""
        self.set_text(self.fortran_text, display_fortran(self.current_fortran), scroll_to_end=True)

    def run_current(
        self,
        *,
        incremental: bool = False,
        source_override: str | None = None,
    ) -> None:
        source = source_override
        if source is None:
            source = self.source_text.get("1.0", "end-1c")
        if not source.strip():
            return
        if is_incomplete_python_source(source):
            self.current_valid = False
            preview = partial_fortran_preview(source)
            self.set_text(self.fortran_text, preview, scroll_to_end=True)
            return
        lines = source.splitlines()
        if not session_has_executable_code(lines):
            return
        result = self.translate_and_run(source.splitlines(), run=True)
        if not result.ok:
            self.invalidate_current_source(result)
            return
        self.current_fortran = result.fortran
        self.current_valid = True
        self.last_diagnostic = ""
        self.set_text(self.fortran_text, display_fortran(self.current_fortran), scroll_to_end=True)
        if result.stdout:
            if incremental:
                text = incremental_output_text(self.last_stdout, result.stdout)
                if text:
                    self.append_output(text)
            else:
                self.append_output(result.stdout)
        if result.stderr:
            self.append_output(result.stderr)
        self.last_stdout = result.stdout

    def translate_and_run(self, lines: list[str], *, run: bool) -> RunResult:
        if not run:
            return translate_session(lines, xp2f=self.xp2f)
        mode = self.compiler_var.get()
        if mode in {"ofort --fast", "ofort"}:
            start = time.perf_counter()
            result = run_session(
                lines,
                xp2f=self.xp2f,
                ofort=self.ofort,
                fast=(mode == "ofort --fast"),
            )
            self.elapsed_var.set(f"run: {time.perf_counter() - start:.3f} s")
            return result

        translated = translate_session(lines, xp2f=self.xp2f)
        if not translated.ok:
            self.elapsed_var.set("")
            return translated
        return self.compile_and_run_fortran(translated.fortran, mode)

    def compile_and_run_fortran(self, fortran: str, mode: str) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="opy_build_") as td:
            tmp = Path(td)
            source = tmp / "opy_session.f90"
            exe = tmp / ("opy_session.exe" if sys.platform.startswith("win") else "opy_session")
            source.write_text(fortran, encoding="utf-8")
            compile_cmd = compiler_command(mode, source, exe)
            start_compile = time.perf_counter()
            try:
                compile_run = subprocess.run(
                    compile_cmd,
                    cwd=str(tmp),
                    text=True,
                    capture_output=True,
                )
            except FileNotFoundError:
                compile_seconds = time.perf_counter() - start_compile
                self.elapsed_var.set(f"compile: {compile_seconds:.3f} s")
                return RunResult(
                    ok=False,
                    fortran=fortran,
                    message=f"{mode} compiler not found",
                )
            compile_seconds = time.perf_counter() - start_compile
            if compile_run.returncode != 0:
                self.elapsed_var.set(f"compile: {compile_seconds:.3f} s")
                return RunResult(
                    ok=False,
                    stdout=compile_run.stdout,
                    stderr=compile_run.stderr,
                    fortran=fortran,
                    message=f"{mode} compile exited with code {compile_run.returncode}",
                )
            start_run = time.perf_counter()
            try:
                program_run = subprocess.run(
                    [str(exe)],
                    cwd=str(tmp),
                    text=True,
                    capture_output=True,
                )
            except FileNotFoundError:
                run_seconds = time.perf_counter() - start_run
                self.elapsed_var.set(f"compile: {compile_seconds:.3f} s  run: {run_seconds:.3f} s")
                return RunResult(
                    ok=False,
                    fortran=fortran,
                    message=f"{mode} did not create executable",
                )
            run_seconds = time.perf_counter() - start_run
            self.elapsed_var.set(f"compile: {compile_seconds:.3f} s  run: {run_seconds:.3f} s")
            return RunResult(
                ok=program_run.returncode == 0,
                stdout=program_run.stdout,
                stderr=program_run.stderr,
                fortran=fortran,
                message="" if program_run.returncode == 0 else f"{mode} run exited with code {program_run.returncode}",
            )

    def open_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Python source",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        try:
            text = source_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror("opy IDE", f"Could not read {source_path}:\n{exc}")
            return
        self.source_path = source_path
        self.set_text(self.source_text, text)
        self.source_text.edit_modified(False)
        self.last_source_text = text
        self.committed_source_text = text
        self.update_fortran()

    def save_source(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save Python source",
            defaultextension=".py",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if path:
            text = self.source_text.get("1.0", "end-1c")
            if text and not text.endswith("\n"):
                text += "\n"
            Path(path).write_text(text, encoding="utf-8")

    def save_fortran(self) -> None:
        if not self.current_fortran:
            self.update_fortran()
        if not self.current_fortran:
            return
        path = filedialog.asksaveasfilename(
            title="Save generated Fortran",
            defaultextension=".f90",
            filetypes=[("Fortran files", "*.f90"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(self.current_fortran, encoding="utf-8")

    def clear_all(self) -> None:
        self.current_fortran = ""
        self.current_valid = False
        self.last_diagnostic = ""
        self.last_source_text = ""
        self.committed_source_text = ""
        self.last_stdout = ""
        self.elapsed_var.set("")
        self.source_path = None
        self.set_text(self.source_text, "")
        self.set_text(self.fortran_text, "")
        self.set_text(self.output_text, "")

    def clear_output(self) -> None:
        self.set_text(self.output_text, "")

    def scroll_fortran_top(self) -> None:
        self.fortran_text.see("1.0")

    def scroll_fortran_bottom(self) -> None:
        self.fortran_text.see(tk.END)

    def invalidate_current_source(self, result: RunResult) -> None:
        message = result.message or "translation failed"
        detail = ""
        if result.stdout:
            detail += result.stdout
        if result.stderr:
            detail += result.stderr
        full = message + ("\n" + detail.rstrip() if detail.strip() else "")
        if full != self.last_diagnostic:
            suffix = ""
            if self.current_fortran:
                suffix = "; Fortran pane shows the last valid translation"
            self.append_output(f"opy: {message}{suffix}\n")
            if detail.strip():
                self.append_output(detail)
                if not detail.endswith("\n"):
                    self.append_output("\n")
            self.last_diagnostic = full

    def append_output(self, text: str) -> None:
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)

    @staticmethod
    def set_text(widget: tk.Text, text: str, *, scroll_to_end: bool = False) -> None:
        previous = str(widget.cget("state"))
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        apply_syntax_highlighting(widget)
        if scroll_to_end:
            widget.see(tk.END)
        widget.configure(state=previous)


def display_fortran(fortran: str) -> str:
    return re.sub(
        r"\A! transpiled by xp2f\.py from .+? on .+?\n",
        "",
        fortran,
        count=1,
    )


def compiler_command(mode: str, source: Path, exe: Path) -> list[str]:
    if mode == "gfortran":
        return ["gfortran", str(source), "-o", str(exe)]
    if mode == "gfortran -O2":
        return ["gfortran", "-O2", str(source), "-o", str(exe)]
    if mode == "gfortran -O3":
        return ["gfortran", "-O3", str(source), "-o", str(exe)]
    if mode == "ifx":
        return ifx_command(source, exe, [])
    if mode == "ifx /O2":
        return ifx_command(source, exe, ["/O2"] if sys.platform.startswith("win") else ["-O2"])
    if mode == "lfortran":
        return ["lfortran", str(source), "-o", str(exe)]
    return ["gfortran", str(source), "-o", str(exe)]


def ifx_command(source: Path, exe: Path, options: list[str]) -> list[str]:
    if sys.platform.startswith("win"):
        return ["ifx", *options, str(source), f"/Fe:{exe}"]
    return ["ifx", *options, str(source), "-o", str(exe)]


PYTHON_KEYWORDS = {
    "False", "None", "True", "and", "as", "break", "class", "continue", "def",
    "elif", "else", "except", "finally", "for", "from", "if", "import", "in",
    "is", "lambda", "not", "or", "pass", "return", "try", "while", "with",
}

FORTRAN_KEYWORDS = {
    "allocatable", "allocate", "call", "contains", "cycle", "deallocate", "do",
    "else", "end", "function", "if", "implicit", "integer", "intent",
    "module", "none", "only", "parameter", "print", "program", "real",
    "result", "return", "subroutine", "then", "use", "while",
}

STRING_PATTERN = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""
NUMBER_PATTERN = r"\b(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\b"


def configure_syntax_tags(widget: tk.Text) -> None:
    widget.tag_configure("syntax_keyword", foreground="#004c99")
    widget.tag_configure("syntax_comment", foreground="#667085")
    widget.tag_configure("syntax_string", foreground="#9a3412")
    widget.tag_configure("syntax_number", foreground="#7c3aed")
    widget.tag_raise("syntax_comment")
    widget.tag_raise("syntax_string")


def apply_syntax_highlighting(widget: tk.Text) -> None:
    language = getattr(widget, "syntax_language", "")
    if language not in {"python", "fortran"}:
        return
    for tag in ("syntax_keyword", "syntax_comment", "syntax_string", "syntax_number"):
        widget.tag_remove(tag, "1.0", tk.END)
    text = widget.get("1.0", "end-1c")
    if not text:
        return
    if language == "python":
        keywords = PYTHON_KEYWORDS
        comment_pattern = r"#[^\n]*"
        flags = 0
    else:
        keywords = FORTRAN_KEYWORDS
        comment_pattern = r"![^\n]*"
        flags = re.IGNORECASE
    apply_pattern_tag(widget, text, STRING_PATTERN, "syntax_string", flags=0)
    apply_pattern_tag(widget, text, comment_pattern, "syntax_comment", flags=0)
    apply_pattern_tag(widget, text, NUMBER_PATTERN, "syntax_number", flags=0)
    keyword_pattern = r"\b(?:" + "|".join(re.escape(word) for word in sorted(keywords, key=len, reverse=True)) + r")\b"
    apply_pattern_tag(widget, text, keyword_pattern, "syntax_keyword", flags=flags)
    widget.tag_raise("syntax_number")
    widget.tag_raise("syntax_keyword")
    widget.tag_raise("syntax_comment")
    widget.tag_raise("syntax_string")


def apply_pattern_tag(widget: tk.Text, text: str, pattern: str, tag: str, *, flags: int) -> None:
    for match in re.finditer(pattern, text, flags):
        start = f"1.0+{match.start()}c"
        end = f"1.0+{match.end()}c"
        widget.tag_add(tag, start, end)


def is_incomplete_python_source(source: str) -> bool:
    try:
        return codeop.compile_command(source, symbol="exec") is None
    except (OverflowError, SyntaxError, ValueError):
        return False


def partial_fortran_preview(source: str) -> str:
    previews = []
    for raw_line in source.splitlines():
        preview = preview_block_header(raw_line)
        if preview:
            previews.append(preview)
    if not previews:
        return "! incomplete Python block; preview only\n"
    return "! incomplete Python block; preview only\n" + "\n".join(previews) + "\n"


def next_line_indent(line: str) -> str:
    base = re.match(r"[ \t]*", line).group(0)
    stripped = line.strip()
    if stripped.endswith(":") and not stripped.startswith("#"):
        return base + "    "
    return base


def immediate_run_append(appended: str) -> bool:
    return bool(appended and "\n" in appended)


def preview_block_header(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.endswith(":"):
        return None
    try:
        tree = ast.parse(stripped + "\n    pass\n", mode="exec")
    except SyntaxError:
        return None
    if len(tree.body) != 1:
        return None
    node = tree.body[0]
    if isinstance(node, ast.For):
        return preview_for_range(node)
    if isinstance(node, ast.If):
        return f"if ({python_expr_to_fortran(node.test)}) then"
    if isinstance(node, ast.While):
        return f"do while ({python_expr_to_fortran(node.test)})"
    return None


def preview_for_range(node: ast.For) -> str | None:
    if not isinstance(node.target, ast.Name):
        return None
    call = node.iter
    if not isinstance(call, ast.Call) or dotted_call_name(call.func) != "range":
        return None
    if call.keywords or not (1 <= len(call.args) <= 3):
        return None
    var = node.target.id
    if len(call.args) == 1:
        start = "0"
        stop = python_expr_to_fortran(call.args[0])
        step = None
    else:
        start = python_expr_to_fortran(call.args[0])
        stop = python_expr_to_fortran(call.args[1])
        step = python_expr_to_fortran(call.args[2]) if len(call.args) == 3 else None
    end = range_end_expr(stop, step)
    if step is None:
        loop = f"do {var} = {start}, {end}"
    else:
        loop = f"do {var} = {start}, {end}, {step}"
    return f"integer :: {var}\n{loop}"


def dotted_call_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return None
    return ".".join(reversed(parts))


def python_expr_to_fortran(node: ast.AST) -> str:
    text = ast.unparse(node)
    text = text.replace(" and ", " .and. ")
    text = text.replace(" or ", " .or. ")
    text = re.sub(r"\bTrue\b", ".true.", text)
    text = re.sub(r"\bFalse\b", ".false.", text)
    return text


def range_end_expr(stop: str, step: str | None) -> str:
    if step is not None and step.strip().startswith("-"):
        return simplify_integer_offset(stop, 1)
    return simplify_integer_offset(stop, -1)


def simplify_integer_offset(expr: str, offset: int) -> str:
    try:
        value = int(expr)
    except ValueError:
        sign = "+" if offset > 0 else "-"
        return f"{expr} {sign} {abs(offset)}"
    return str(value + offset)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worksheet-style GUI for opy.")
    parser.add_argument("--xp2f", default=str(DEFAULT_XP2F), help="path to xp2f.py")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help="ofort command")
    parser.add_argument("--no-fast", action="store_true", help="start with ofort --fast disabled")
    parser.add_argument("--compiler", choices=COMPILER_MODES, help="initial compiler dropdown selection")
    parser.add_argument("--immediate", action="store_true", help="start with immediate run enabled")
    args = parser.parse_args(argv)
    xp2f = Path(args.xp2f)
    if not xp2f.exists():
        print(f"opy IDE: xp2f.py not found: {xp2f}", file=sys.stderr)
        return 1

    root = tk.Tk()
    OpyIde(
        root,
        xp2f=str(xp2f),
        ofort=args.ofort,
        fast=not args.no_fast,
        compiler=args.compiler,
        immediate=args.immediate,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
