#!/usr/bin/env python3
"""Small worksheet-style IDE for omat."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from omat import (
    DEFAULT_OFORT,
    OmatError,
    compile_and_run_capture,
    line_closes_block,
    line_opens_block,
    run_with_ofort_capture,
    translate_source,
    validate_partial_source,
)


class OmatIde:
    def __init__(
        self,
        root: tk.Tk,
        *,
        ofort: str,
        gfortran: str,
        generic: bool = False,
        fast: bool = True,
    ) -> None:
        self.root = root
        self.ofort = ofort
        self.gfortran = gfortran
        self.generic = tk.BooleanVar(value=generic)
        self.fast = tk.BooleanVar(value=fast)
        self.source_lines: list[str] = []
        self.block_depth = 0
        self.current_fortran = ""
        self.source_path: Path | None = None

        root.title("omat IDE")
        root.geometry("1100x750")
        self.build_ui()
        self.update_fortran()

    def build_ui(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)

        ttk.Button(toolbar, text="Open", command=self.open_source).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save MATLAB", command=self.save_source).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(toolbar, text="Save Fortran", command=self.save_fortran).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Run", command=self.run_current).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(
            toolbar,
            text="Generic Fortran",
            variable=self.generic,
            command=self.update_fortran,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            toolbar,
            text="ofort --fast",
            variable=self.fast,
        ).pack(side=tk.LEFT, padx=(12, 0))

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=1)

        ttk.Label(left, text="MATLAB/Octave input").pack(anchor=tk.W)
        self.source_text = tk.Text(left, wrap=tk.NONE, undo=False)
        self.source_text.pack(fill=tk.BOTH, expand=True)
        self.source_text.configure(state=tk.DISABLED)

        ttk.Label(right, text="Generated Fortran").pack(anchor=tk.W)
        self.fortran_text = tk.Text(right, wrap=tk.NONE, undo=False)
        self.fortran_text.pack(fill=tk.BOTH, expand=True)
        self.fortran_text.configure(state=tk.DISABLED)

        input_row = ttk.Frame(self.root)
        input_row.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(input_row, text="omat>").pack(side=tk.LEFT)
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
        if self.try_accept_line(line):
            self.entry.delete(0, tk.END)

    def try_accept_line(self, line: str) -> bool:
        candidate = [*self.source_lines, line]
        next_depth = self.block_depth
        if line_opens_block(line):
            next_depth += 1
        elif line_closes_block(line) and next_depth > 0:
            next_depth -= 1

        try:
            if next_depth > 0:
                validate_partial_source("\n".join(candidate))
            else:
                translate_source(
                    "\n".join(candidate),
                    generic=self.generic.get(),
                    source_path=self.source_path,
                )
        except OmatError as exc:
            self.append_output(f"omat: {exc}\n")
            return False

        self.source_lines = candidate
        self.block_depth = next_depth
        self.refresh_source_text()
        if self.block_depth == 0:
            self.update_fortran()
        else:
            self.append_output("accepted; waiting for matching end\n")
        return True

    def update_fortran(self) -> None:
        source = "\n".join(self.source_lines)
        if not source.strip():
            self.current_fortran = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
            return
        try:
            self.current_fortran = translate_source(
                source,
                generic=self.generic.get(),
                source_path=self.source_path,
            )
        except OmatError as exc:
            self.current_fortran = ""
            self.set_text(self.fortran_text, "", scroll_to_end=True)
            self.append_output(f"omat: {exc}\n")
            return
        self.set_text(self.fortran_text, self.current_fortran, scroll_to_end=True)

    def run_current(self) -> None:
        if self.block_depth != 0:
            self.append_output("omat: cannot run until the current block is closed\n")
            return
        if not self.current_fortran:
            self.update_fortran()
        if not self.current_fortran:
            return
        if self.generic.get():
            result = compile_and_run_capture(self.current_fortran, self.gfortran)
        elif "use ofort_la_mod" in self.current_fortran or "use ofort_random_mod" in self.current_fortran:
            result = run_with_ofort_capture(self.current_fortran, self.ofort, fast=self.fast.get())
        else:
            result = compile_and_run_capture(self.current_fortran, self.gfortran)
        if result.stdout:
            self.append_output(result.stdout)
        if result.stderr:
            self.append_output(result.stderr)
        self.append_output(f"exit code: {result.returncode}\n")

    def open_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Open MATLAB/Octave source",
            filetypes=[("MATLAB files", "*.m"), ("All files", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        try:
            lines = source_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            messagebox.showerror("omat IDE", f"Could not read {source_path}:\n{exc}")
            return
        old_lines = self.source_lines
        old_path = self.source_path
        old_depth = self.block_depth
        self.source_lines = []
        self.source_path = source_path
        self.block_depth = 0
        for line in lines:
            if not line.strip():
                self.source_lines.append(line)
                continue
            if not self.try_accept_line(line):
                self.source_lines = old_lines
                self.source_path = old_path
                self.block_depth = old_depth
                self.refresh_source_text()
                self.update_fortran()
                return
        self.refresh_source_text()
        self.update_fortran()

    def save_source(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save MATLAB/Octave source",
            defaultextension=".m",
            filetypes=[("MATLAB files", "*.m"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text("\n".join(self.source_lines) + "\n", encoding="utf-8")

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
        self.source_lines.clear()
        self.block_depth = 0
        self.current_fortran = ""
        self.source_path = None
        self.refresh_source_text()
        self.set_text(self.fortran_text, "")
        self.set_text(self.output_text, "")

    def refresh_source_text(self) -> None:
        text = "\n".join(self.source_lines)
        if text:
            text += "\n"
        self.set_text(self.source_text, text)

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


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worksheet-style GUI for omat.")
    parser.add_argument("--ofort", default=str(DEFAULT_OFORT), help="ofort command")
    parser.add_argument("--gfortran", default="gfortran", help="gfortran command")
    parser.add_argument("--generic", action="store_true", help="start in generic Fortran mode")
    parser.add_argument("--no-fast", action="store_true", help="start with ofort --fast disabled")
    args = parser.parse_args(argv)

    root = tk.Tk()
    OmatIde(root, ofort=args.ofort, gfortran=args.gfortran, generic=args.generic, fast=not args.no_fast)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
