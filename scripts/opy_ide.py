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
    repl_source,
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


def make_scrollable_text(
    parent: tk.Widget,
    *,
    wrap: str,
    undo: bool,
    height: int | None = None,
) -> tk.Text:
    frame = ttk.Frame(parent)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    options: dict[str, object] = {"wrap": wrap, "undo": undo}
    if height is not None:
        options["height"] = height
    text = tk.Text(frame, **options)

    yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
    text.configure(yscrollcommand=yscroll.set)
    text.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")

    text._scroll_frame = frame  # type: ignore[attr-defined]
    text._yscrollbar = yscroll  # type: ignore[attr-defined]
    text.bind("<MouseWheel>", lambda event: scroll_text_vertical(text, event))
    return text


def scroll_text_vertical(text: tk.Text, event: tk.Event) -> str:
    delta = int(-1 * (event.delta / 120))
    if delta == 0:
        delta = -1 if event.delta > 0 else 1
    text.yview_scroll(delta, "units")
    return "break"


class OpyIde:
    def __init__(
        self,
        root: tk.Tk,
        *,
        xp2f: str,
        ofort: str,
        fast: bool = True,
        compiler: str | None = None,
        immediate: bool = True,
        source: Path | None = None,
    ) -> None:
        self.root = root
        self.xp2f = Path(xp2f)
        self.ofort = ofort
        initial_compiler = compiler if compiler in COMPILER_MODES else ("ofort --fast" if fast else "ofort")
        self.compiler_var = tk.StringVar(value=initial_compiler)
        self.fortran_mode = tk.StringVar(value="ofort-optimized")
        self.immediate = tk.BooleanVar(value=immediate)
        self.show_python_output = tk.BooleanVar(value=False)
        self.manual_fortran = tk.BooleanVar(value=False)
        self.explain_helpers = tk.BooleanVar(value=True)
        self.fortran_title = tk.StringVar(value="Generated Fortran")
        self.output_decimals = tk.StringVar(value="")
        self.update_job: str | None = None
        self.highlight_job: str | None = None
        self.current_fortran = ""
        self.current_valid = False
        self.last_diagnostic = ""
        self.last_source_text = ""
        self.committed_source_text = ""
        self.last_stdout = ""
        self.elapsed_var = tk.StringVar(value="")
        self.python_elapsed_var = tk.StringVar(value="")
        self.source_path: Path | None = None

        root.title("opy IDE")
        root.geometry("1100x750")
        self.build_ui()
        if source is not None:
            self.load_source_file(source)
        else:
            self.update_fortran()

    def build_ui(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)

        ttk.Button(toolbar, text="Open", command=self.open_source).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save Python", command=self.save_source).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Save Fortran", command=self.save_fortran).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Run Python", command=self.run_python_current).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Run Fortran", command=self.run_current).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Run Both", command=self.run_both).pack(side=tk.LEFT, padx=(4, 0))
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
        ttk.Label(toolbar, text="Fortran:").pack(side=tk.LEFT, padx=(12, 4))
        mode_box = ttk.Combobox(
            toolbar,
            textvariable=self.fortran_mode,
            values=["ofort-optimized", "generic"],
            width=15,
            state="readonly",
        )
        mode_box.pack(side=tk.LEFT)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self.regenerate_fortran())
        ttk.Checkbutton(toolbar, text="Immediate run", variable=self.immediate).pack(side=tk.LEFT, padx=(12, 0))

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        python_header = ttk.Frame(left)
        python_header.pack(fill=tk.X)
        ttk.Label(python_header, text="Python input").pack(side=tk.LEFT)
        ttk.Button(python_header, text="Indent Block", command=self.indent_block_at_cursor).pack(side=tk.RIGHT)
        self.source_text = tk.Text(left, wrap=tk.NONE, undo=True)
        self.source_text.syntax_language = "python"
        self.source_text.pack(fill=tk.BOTH, expand=True)
        self.source_text.bind("<<Modified>>", self.source_modified)
        self.source_text.bind("<Return>", self.source_return_event)
        configure_syntax_tags(self.source_text)

        fortran_header = ttk.Frame(right)
        fortran_header.pack(fill=tk.X)
        ttk.Label(fortran_header, textvariable=self.fortran_title).pack(side=tk.LEFT)
        ttk.Checkbutton(
            fortran_header,
            text="Edit Fortran",
            variable=self.manual_fortran,
            command=self.toggle_manual_fortran,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(fortran_header, text="Regenerate", command=self.regenerate_fortran).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(
            fortran_header,
            text="Explain helpers",
            variable=self.explain_helpers,
            command=self.regenerate_fortran,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(fortran_header, text="Top", command=self.scroll_fortran_top).pack(side=tk.RIGHT)
        ttk.Button(fortran_header, text="Bottom", command=self.scroll_fortran_bottom).pack(side=tk.RIGHT, padx=(0, 4))
        self.fortran_text = make_scrollable_text(right, wrap=tk.NONE, undo=False)
        self.fortran_text.syntax_language = "fortran"
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
        ttk.Label(output_row, text="Decimals:").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Spinbox(
            output_row,
            from_=0,
            to=16,
            width=4,
            textvariable=self.output_decimals,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            output_row,
            text="Show Python output",
            variable=self.show_python_output,
            command=self.update_output_layout,
        ).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(output_row, text="Clear Output", command=self.clear_output).pack(side=tk.RIGHT)

        self.output_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.output_pane.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=6, pady=(0, 6))
        self.python_output_frame = ttk.Frame(self.output_pane)
        self.fortran_output_frame = ttk.Frame(self.output_pane)
        python_output_header = ttk.Frame(self.python_output_frame)
        python_output_header.pack(fill=tk.X)
        ttk.Label(python_output_header, text="Python output").pack(side=tk.LEFT)
        ttk.Label(python_output_header, textvariable=self.python_elapsed_var).pack(side=tk.RIGHT)
        self.python_output_text = tk.Text(self.python_output_frame, height=10, wrap=tk.WORD, undo=False)
        self.python_output_text.pack(fill=tk.BOTH, expand=True)
        fortran_output_header = ttk.Frame(self.fortran_output_frame)
        fortran_output_header.pack(fill=tk.X)
        ttk.Label(fortran_output_header, text="Fortran output").pack(side=tk.LEFT)
        ttk.Label(fortran_output_header, textvariable=self.elapsed_var).pack(side=tk.RIGHT)
        self.output_text = tk.Text(self.fortran_output_frame, height=10, wrap=tk.WORD, undo=False)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.update_output_layout()
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
            if not self.manual_fortran.get():
                self.set_text(self.fortran_text, "", scroll_to_end=True)
        elif not source.startswith(self.last_source_text):
            self.last_stdout = ""

    def source_return_event(self, _event: tk.Event) -> None:
        line = self.source_text.get("insert linestart", "insert lineend")
        indent = next_line_indent(line)
        self.source_text.insert(tk.INSERT, "\n" + indent)
        if indent:
            self.auto_indent_existing_block_after_header()
        self.root.after_idle(self.commit_source_change)
        return "break"

    def auto_indent_existing_block_after_header(self) -> None:
        header_index = self.source_text.index("insert -1 lines linestart")
        changed = indent_existing_block_after_header(self.source_text, header_index)
        if changed:
            self.source_text.edit_modified(True)

    def indent_block_at_cursor(self) -> None:
        index = self.source_text.index("insert linestart")
        line = self.source_text.get(f"{index} linestart", f"{index} lineend")
        if not is_python_block_header(line):
            previous = self.source_text.index(f"{index} -1 lines linestart")
            previous_line = self.source_text.get(f"{previous} linestart", f"{previous} lineend")
            if is_python_block_header(previous_line):
                index = previous
            else:
                return
        changed = indent_existing_block_after_header(self.source_text, index)
        if changed:
            self.source_text.edit_modified(True)
            self.commit_source_change()

    def commit_source_change(self) -> None:
        source = self.source_text.get("1.0", "end-1c")
        self.committed_source_text = source
        if not self.manual_fortran.get():
            self.schedule_update_fortran(source)
        if self.immediate.get() and not self.manual_fortran.get() and source.startswith(self.last_source_text):
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
        if self.manual_fortran.get():
            return
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
        self.show_generated_fortran()

    def run_current(
        self,
        *,
        incremental: bool = False,
        source_override: str | None = None,
    ) -> None:
        if self.manual_fortran.get() and source_override is None:
            result = self.run_fortran_text(self.current_fortran_text())
            if result.ok:
                if result.stdout:
                    self.append_output(result.stdout)
                if result.stderr:
                    self.append_output(result.stderr)
                self.last_stdout = result.stdout
            else:
                self.invalidate_current_source(result)
            return
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
        self.show_generated_fortran()
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

    def run_python_current(self) -> None:
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
        self.show_python_output.set(True)
        self.update_output_layout()
        python_result = self.run_python_source(lines)
        if python_result.stdout:
            self.append_python_output(python_result.stdout)
        if python_result.stderr:
            self.append_python_output(python_result.stderr)
        if not python_result.ok and python_result.message:
            self.append_python_output(f"opy: {python_result.message}\n")

    def run_both(self) -> None:
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
        self.show_python_output.set(True)
        self.update_output_layout()
        python_result = self.run_python_source(lines)
        if python_result.stdout:
            self.append_python_output(python_result.stdout)
        if python_result.stderr:
            self.append_python_output(python_result.stderr)
        if not python_result.ok and python_result.message:
            self.append_python_output(f"opy: {python_result.message}\n")

        if self.manual_fortran.get():
            fortran_result = self.run_fortran_text(self.current_fortran_text())
        else:
            fortran_result = self.translate_and_run(lines, run=True)
        if fortran_result.ok:
            self.current_fortran = fortran_result.fortran
            self.current_valid = True
            self.last_diagnostic = ""
            if not self.manual_fortran.get():
                self.show_generated_fortran()
            if fortran_result.stdout:
                self.append_output(fortran_result.stdout)
            if fortran_result.stderr:
                self.append_output(fortran_result.stderr)
            self.last_stdout = fortran_result.stdout
        else:
            self.invalidate_current_source(fortran_result)

    def translate_and_run(self, lines: list[str], *, run: bool) -> RunResult:
        if not run:
            return translate_session(
                lines,
                xp2f=self.xp2f,
                generic=self.use_generic_fortran(),
                explain_helpers=self.explain_helpers.get(),
            )
        mode = self.compiler_var.get()
        if mode in {"ofort --fast", "ofort"}:
            start = time.perf_counter()
            result = run_session(
                lines,
                xp2f=self.xp2f,
                ofort=self.ofort,
                fast=(mode == "ofort --fast"),
                generic=self.use_generic_fortran(),
                explain_helpers=self.explain_helpers.get(),
            )
            self.elapsed_var.set(f"run: {time.perf_counter() - start:.3f} s")
            return result

        translated = translate_session(
            lines,
            xp2f=self.xp2f,
            generic=self.use_generic_fortran(),
            explain_helpers=self.explain_helpers.get(),
        )
        if not translated.ok:
            self.elapsed_var.set("")
            return translated
        return self.compile_and_run_fortran(translated.fortran, mode)

    def use_generic_fortran(self) -> bool:
        return self.fortran_mode.get() == "generic"

    def run_fortran_text(self, fortran: str) -> RunResult:
        if not fortran.strip():
            return RunResult(ok=True, fortran=fortran)
        mode = self.compiler_var.get()
        if mode in {"ofort --fast", "ofort"}:
            with tempfile.TemporaryDirectory(prefix="opy_manual_") as td:
                tmp = Path(td)
                source = tmp / "opy_manual.f90"
                source.write_text(fortran, encoding="utf-8")
                cmd = [self.ofort]
                if mode == "ofort --fast":
                    cmd.append("--fast")
                cmd.append(str(source))
                start = time.perf_counter()
                try:
                    ofort_run = subprocess.run(
                        cmd,
                        cwd=str(Path.cwd()),
                        text=True,
                        capture_output=True,
                    )
                except FileNotFoundError:
                    self.elapsed_var.set(f"run: {time.perf_counter() - start:.3f} s")
                    return RunResult(ok=False, fortran=fortran, message="ofort compiler not found")
                self.elapsed_var.set(f"run: {time.perf_counter() - start:.3f} s")
                return RunResult(
                    ok=ofort_run.returncode == 0,
                    stdout=ofort_run.stdout,
                    stderr=ofort_run.stderr,
                    fortran=fortran,
                    message="" if ofort_run.returncode == 0 else f"ofort exited with code {ofort_run.returncode}",
                )
        return self.compile_and_run_fortran(fortran, mode)

    def run_python_source(self, lines: list[str]) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="opy_python_") as td:
            tmp = Path(td)
            source = tmp / "opy_session.py"
            source.write_text(repl_source(lines), encoding="utf-8")
            start = time.perf_counter()
            python_run = subprocess.run(
                [sys.executable, str(source)],
                cwd=str(Path.cwd()),
                text=True,
                capture_output=True,
            )
            self.python_elapsed_var.set(f"run: {time.perf_counter() - start:.3f} s")
            return RunResult(
                ok=python_run.returncode == 0,
                stdout=python_run.stdout,
                stderr=python_run.stderr,
                message="" if python_run.returncode == 0 else f"Python exited with code {python_run.returncode}",
            )

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
        self.load_source_file(Path(path), show_errors=True)

    def load_source_file(self, source_path: Path, *, show_errors: bool = False) -> bool:
        try:
            text = source_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            if show_errors:
                messagebox.showerror("opy IDE", f"Could not read {source_path}:\n{exc}")
            else:
                print(f"opy IDE: could not read {source_path}: {exc}", file=sys.stderr)
            return False
        self.source_path = source_path
        self.set_text(self.source_text, text)
        self.source_text.edit_modified(False)
        self.last_source_text = text
        self.committed_source_text = text
        self.update_fortran()
        return True

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
        fortran = self.current_fortran_text()
        if not fortran and not self.manual_fortran.get():
            self.update_fortran()
            fortran = self.current_fortran_text()
        if not fortran:
            return
        path = filedialog.asksaveasfilename(
            title="Save Fortran",
            defaultextension=".f90",
            filetypes=[("Fortran files", "*.f90"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(fortran, encoding="utf-8")

    def clear_all(self) -> None:
        self.manual_fortran.set(False)
        self.toggle_manual_fortran()
        self.current_fortran = ""
        self.current_valid = False
        self.last_diagnostic = ""
        self.last_source_text = ""
        self.committed_source_text = ""
        self.last_stdout = ""
        self.elapsed_var.set("")
        self.python_elapsed_var.set("")
        self.source_path = None
        self.set_text(self.source_text, "")
        self.set_text(self.fortran_text, "")
        self.set_text(self.output_text, "")
        self.set_text(self.python_output_text, "")

    def current_fortran_text(self) -> str:
        text = self.fortran_text.get("1.0", "end-1c")
        return text if self.manual_fortran.get() else self.current_fortran

    def toggle_manual_fortran(self) -> None:
        if self.manual_fortran.get():
            self.fortran_title.set("Fortran (manual edit)")
            self.fortran_text.configure(state=tk.NORMAL)
        else:
            self.fortran_title.set("Generated Fortran")
            self.current_fortran = self.fortran_text.get("1.0", "end-1c")
            self.fortran_text.configure(state=tk.DISABLED)

    def regenerate_fortran(self) -> None:
        self.manual_fortran.set(False)
        self.toggle_manual_fortran()
        self.update_fortran()

    def clear_output(self) -> None:
        self.set_text(self.output_text, "")
        self.set_text(self.python_output_text, "")

    def update_output_layout(self) -> None:
        panes = set(self.output_pane.panes())
        python_name = str(self.python_output_frame)
        fortran_name = str(self.fortran_output_frame)
        if python_name in panes:
            self.output_pane.forget(self.python_output_frame)
        if fortran_name in panes:
            self.output_pane.forget(self.fortran_output_frame)
        if self.show_python_output.get():
            self.output_pane.add(self.python_output_frame, weight=1)
            self.output_pane.add(self.fortran_output_frame, weight=1)
        else:
            self.output_pane.add(self.fortran_output_frame, weight=1)

    def scroll_fortran_top(self) -> None:
        self.fortran_text.see("1.0")

    def scroll_fortran_bottom(self) -> None:
        self.fortran_text.see(tk.END)

    def show_generated_fortran(self) -> None:
        self.set_text(self.fortran_text, display_fortran(self.current_fortran))
        self.fortran_text.see("1.0")

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
        self.output_text.insert(tk.END, self.format_output_text(text))
        self.output_text.see(tk.END)

    def append_python_output(self, text: str) -> None:
        self.python_output_text.configure(state=tk.NORMAL)
        self.python_output_text.insert(tk.END, self.format_output_text(text))
        self.python_output_text.see(tk.END)

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


FLOAT_TOKEN_PATTERN = re.compile(
    r"(?<![\w.])([+-]?(?:(?:\d+\.\d*|\.\d+)(?:[eEdD][+-]?\d+)?|\d+[eEdD][+-]?\d+))(?![\w.])"
)


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
    widget.tag_configure("syntax_function", foreground="#0f766e")
    widget.tag_configure("syntax_module", foreground="#5b21b6")
    widget.tag_configure("syntax_comment", foreground="#667085")
    widget.tag_configure("syntax_string", foreground="#9a3412")
    widget.tag_configure("syntax_number", foreground="#7c3aed")
    widget.tag_raise("syntax_comment")
    widget.tag_raise("syntax_string")


def apply_syntax_highlighting(widget: tk.Text) -> None:
    language = getattr(widget, "syntax_language", "")
    if language not in {"python", "fortran"}:
        return
    for tag in (
        "syntax_keyword",
        "syntax_function",
        "syntax_module",
        "syntax_comment",
        "syntax_string",
        "syntax_number",
    ):
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
    if language == "python":
        apply_python_call_tags(widget, text)
    else:
        apply_pattern_group_tag(
            widget,
            text,
            r"\b([A-Za-z_]\w*)\s*(?=\()",
            "syntax_function",
            group=1,
            flags=re.IGNORECASE,
        )
    keyword_pattern = r"\b(?:" + "|".join(re.escape(word) for word in sorted(keywords, key=len, reverse=True)) + r")\b"
    apply_pattern_tag(widget, text, keyword_pattern, "syntax_keyword", flags=flags)
    widget.tag_raise("syntax_number")
    widget.tag_raise("syntax_module")
    widget.tag_raise("syntax_function")
    widget.tag_raise("syntax_keyword")
    widget.tag_raise("syntax_comment")
    widget.tag_raise("syntax_string")


def apply_pattern_tag(widget: tk.Text, text: str, pattern: str, tag: str, *, flags: int) -> None:
    for match in re.finditer(pattern, text, flags):
        start = f"1.0+{match.start()}c"
        end = f"1.0+{match.end()}c"
        widget.tag_add(tag, start, end)


def apply_pattern_group_tag(
    widget: tk.Text,
    text: str,
    pattern: str,
    tag: str,
    *,
    group: int,
    flags: int,
) -> None:
    for match in re.finditer(pattern, text, flags):
        start = f"1.0+{match.start(group)}c"
        end = f"1.0+{match.end(group)}c"
        widget.tag_add(tag, start, end)


def apply_python_call_tags(widget: tk.Text, text: str) -> None:
    dotted_pattern = r"\b([A-Za-z_]\w*)(?:\s*\.\s*([A-Za-z_]\w*))*\s*(?=\()"
    for match in re.finditer(dotted_pattern, text):
        call_text = text[match.start():match.end()]
        names = list(re.finditer(r"[A-Za-z_]\w*", call_text))
        if not names:
            continue
        if len(names) > 1:
            for name_match in names[:-1]:
                start = match.start() + name_match.start()
                end = match.start() + name_match.end()
                widget.tag_add("syntax_module", f"1.0+{start}c", f"1.0+{end}c")
        function_match = names[-1]
        start = match.start() + function_match.start()
        end = match.start() + function_match.end()
        widget.tag_add("syntax_function", f"1.0+{start}c", f"1.0+{end}c")


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
    if is_python_block_header(line):
        return base + "    "
    return base


def is_python_block_header(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped.endswith(":") and stripped and not stripped.startswith("#"))


def indent_existing_block_after_header(widget: tk.Text, header_index: str) -> bool:
    header_line = widget.get(f"{header_index} linestart", f"{header_index} lineend")
    if not is_python_block_header(header_line):
        return False
    base_indent = re.match(r"[ \t]*", header_line).group(0)
    child_indent = base_indent + "    "
    line_no = int(widget.index(f"{header_index} lineend").split(".", 1)[0]) + 1
    end_line_no = int(widget.index("end-1c").split(".", 1)[0])
    changed = False
    while line_no <= end_line_no:
        start = f"{line_no}.0"
        line = widget.get(start, f"{line_no}.0 lineend")
        if not line.strip():
            break
        indent = re.match(r"[ \t]*", line).group(0)
        if len(indent.expandtabs(4)) < len(base_indent.expandtabs(4)):
            break
        if indent.startswith(child_indent) or len(indent.expandtabs(4)) > len(base_indent.expandtabs(4)):
            line_no += 1
            continue
        if indent == base_indent:
            widget.insert(start, "    ")
            changed = True
            line_no += 1
            continue
        break
    return changed


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
    parser.add_argument("source_file", nargs="?", help="optional Python source file to open")
    parser.add_argument("--source", help="Python source file to open; overrides positional source")
    parser.add_argument("--xp2f", default=str(DEFAULT_XP2F), help="path to xp2f.py")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help="ofort command")
    parser.add_argument("--no-fast", action="store_true", help="start with ofort --fast disabled")
    parser.add_argument("--compiler", choices=COMPILER_MODES, help="initial compiler dropdown selection")
    parser.add_argument("--no-immediate", action="store_true", help="start with immediate run disabled")
    args = parser.parse_args(argv)
    xp2f = Path(args.xp2f)
    if not xp2f.exists():
        print(f"opy IDE: xp2f.py not found: {xp2f}", file=sys.stderr)
        return 1
    source_arg = args.source or args.source_file
    source = Path(source_arg) if source_arg else None
    if source is not None and not source.exists():
        print(f"opy IDE: source file not found: {source}", file=sys.stderr)
        return 1

    root = tk.Tk()
    OpyIde(
        root,
        xp2f=str(xp2f),
        ofort=args.ofort,
        fast=not args.no_fast,
        compiler=args.compiler,
        immediate=not args.no_immediate,
        source=source,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
