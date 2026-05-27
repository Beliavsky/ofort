#!/usr/bin/env python3
"""Small worksheet-style IDE for opy."""

from __future__ import annotations

import argparse
import re
import sys
import tkinter as tk
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
)


class OpyIde:
    def __init__(
        self,
        root: tk.Tk,
        *,
        xp2f: str,
        ofort: str,
        fast: bool = True,
        immediate: bool = False,
    ) -> None:
        self.root = root
        self.xp2f = Path(xp2f)
        self.ofort = ofort
        self.fast = tk.BooleanVar(value=fast)
        self.immediate = tk.BooleanVar(value=immediate)
        self.update_job: str | None = None
        self.current_fortran = ""
        self.current_valid = False
        self.last_diagnostic = ""
        self.last_source_text = ""
        self.last_stdout = ""
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
        ttk.Button(toolbar, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(toolbar, text="ofort --fast", variable=self.fast).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(toolbar, text="Immediate run", variable=self.immediate).pack(side=tk.LEFT, padx=(12, 0))

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        ttk.Label(left, text="Python input").pack(anchor=tk.W)
        self.source_text = tk.Text(left, wrap=tk.NONE, undo=True)
        self.source_text.pack(fill=tk.BOTH, expand=True)
        self.source_text.bind("<<Modified>>", self.source_modified)

        ttk.Label(right, text="Generated Fortran").pack(anchor=tk.W)
        self.fortran_text = tk.Text(right, wrap=tk.NONE, undo=False)
        self.fortran_text.pack(fill=tk.BOTH, expand=True)
        self.fortran_text.configure(state=tk.DISABLED)

        input_row = ttk.Frame(self.root)
        input_row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(input_row, text="opy>").pack(side=tk.LEFT)
        self.entry = ttk.Entry(input_row)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.entry.bind("<Return>", self.submit_line_event)
        ttk.Button(input_row, text="Enter", command=self.submit_line).pack(side=tk.LEFT)

        ttk.Label(self.root, text="Output").pack(anchor=tk.W, padx=6)
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
        self.schedule_update_fortran()

    def source_modified(self, _event: tk.Event) -> None:
        if not self.source_text.edit_modified():
            return
        self.source_text.edit_modified(False)
        source = self.source_text.get("1.0", "end-1c")
        self.schedule_update_fortran()
        if self.immediate.get() and source.startswith(self.last_source_text):
            appended = source[len(self.last_source_text):]
            if appended and appended.endswith("\n"):
                self.root.after(350, lambda: self.run_current(show_exit=False, incremental=True))
        elif not source.startswith(self.last_source_text):
            self.last_stdout = ""
        self.last_source_text = source

    def schedule_update_fortran(self) -> None:
        if self.update_job is not None:
            self.root.after_cancel(self.update_job)
        self.update_job = self.root.after(300, self.update_fortran)

    def update_fortran(self) -> None:
        self.update_job = None
        source = self.source_text.get("1.0", "end-1c")
        if not source.strip():
            self.current_fortran = ""
            self.current_valid = False
            self.last_diagnostic = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
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

    def run_current(self, *, show_exit: bool = True, incremental: bool = False) -> None:
        source = self.source_text.get("1.0", "end-1c")
        if not source.strip():
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
        if show_exit and (result.stdout or result.stderr):
            self.append_output("exit code: 0\n")
        self.last_stdout = result.stdout

    def translate_and_run(self, lines: list[str], *, run: bool) -> RunResult:
        if run:
            return run_session(lines, xp2f=self.xp2f, ofort=self.ofort, fast=self.fast.get())
        return run_session(lines, xp2f=self.xp2f, ofort=self.ofort, fast=self.fast.get())

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
        self.last_stdout = ""
        self.source_path = None
        self.set_text(self.source_text, "")
        self.set_text(self.fortran_text, "")
        self.set_text(self.output_text, "")

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


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worksheet-style GUI for opy.")
    parser.add_argument("--xp2f", default=str(DEFAULT_XP2F), help="path to xp2f.py")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help="ofort command")
    parser.add_argument("--no-fast", action="store_true", help="start with ofort --fast disabled")
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
        immediate=args.immediate,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
