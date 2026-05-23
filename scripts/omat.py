#!/usr/bin/env python3
"""Translate a small MATLAB/Octave-like numerical subset to Fortran and run it."""

from __future__ import annotations

import argparse
import ast
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFORT = ROOT / ("ofort.exe" if sys.platform.startswith("win") else "ofort")

IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d+\.\d*|\.\d+|\d+)(?:[eEdD][+-]?\d+)?(?![A-Za-z0-9_])"
)
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)


BUILTINS = {
    "abs",
    "acos",
    "asin",
    "atan",
    "cos",
    "equicor",
    "exp",
    "log",
    "maxval",
    "mean",
    "minval",
    "sqrt",
    "sin",
    "size",
    "sum",
    "tan",
}

MATRIX_FUNC_RE = re.compile(r"^(rand|zeros|ones)\s*\((.*)\)$", re.IGNORECASE)
LA_SCALAR_FUNCTIONS = {"trace", "det", "cond", "norm", "rank", "is_square", "is_diagonal", "is_symmetric", "is_invertible"}
LA_VECTOR_FUNCTIONS = {"eig", "svd"}
LA_MATRIX_FUNCTIONS = {"eye", "triu", "tril", "kron", "inv", "qr", "lu", "pinv", "chol", "outer_product", "transpose2", "matmul2", "crossprod", "tcrossprod"}
LA_FUNCTIONS = LA_SCALAR_FUNCTIONS | LA_VECTOR_FUNCTIONS | LA_MATRIX_FUNCTIONS | {"diag", "solve", "mldivide", "col_sums", "col_means"}


@dataclass
class Symbol:
    name: str
    kind: str


@dataclass
class Statement:
    text: str
    indent: int


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


class OmatError(Exception):
    pass


class Translator:
    def __init__(self) -> None:
        self.symbols: dict[str, Symbol] = {}
        self.statements: list[Statement] = []
        self.indent = 0
        self.needs_linstep = False
        self.needs_la_mod = False
        self.la_names: set[str] = set()

    def translate(self, source: str) -> str:
        for line_no, raw in enumerate(source.splitlines(), start=1):
            self.add_line(raw, line_no)
        if self.indent != 0:
            raise OmatError("unterminated block: missing end")
        return self.emit_fortran()

    def add_line(self, raw: str, line_no: int) -> None:
        line = strip_comment(raw).strip()
        if not line:
            return
        suppress_output = line.endswith(";")
        if suppress_output:
            line = line[:-1].rstrip()
        if not line:
            return

        low = line.lower()
        if low == "end":
            if self.indent <= 0:
                raise OmatError(f"line {line_no}: END without a block")
            self.indent -= 1
            self.statements.append(Statement("end do", self.indent))
            return

        m = FOR_RE.match(line)
        if m:
            var, spec = m.groups()
            self.symbols.setdefault(var.lower(), Symbol(var, "integer"))
            start, stop, step = parse_loop_spec(spec)
            if step is None:
                self.statements.append(
                    Statement(
                        f"do {var} = {self.expr(start)}, {self.expr(stop)}",
                        self.indent,
                    )
                )
            else:
                self.statements.append(
                    Statement(
                        f"do {var} = {self.expr(start)}, {self.expr(stop)}, {self.expr(step)}",
                        self.indent,
                    )
                )
            self.indent += 1
            return

        if low.startswith("disp(") and line.endswith(")"):
            arg = line[line.find("(") + 1 : -1]
            if not suppress_output:
                self.emit_display(arg)
            return

        m = ASSIGN_RE.match(line)
        if m:
            name, rhs = m.groups()
            kind = self.infer_kind(rhs)
            existing = self.symbols.get(name.lower())
            if existing is not None and existing.kind != kind:
                raise OmatError(
                    f"line {line_no}: variable '{name}' changes from {existing.kind} to {kind}"
                )
            self.symbols[name.lower()] = Symbol(name, kind)
            self.statements.append(Statement(f"{name} = {self.expr(rhs)}", self.indent))
            if not suppress_output:
                if kind == "real_matrix":
                    self.statements.append(Statement(f"call print_matrix_omat({name})", self.indent))
                else:
                    self.statements.append(Statement(f"print *, {name}", self.indent))
            return

        if not suppress_output:
            self.emit_display(line)

    def emit_display(self, value: str) -> None:
        stripped = value.strip()
        kind = self.infer_kind(stripped)
        if kind == "real_matrix":
            self.statements.append(Statement(f"call print_matrix_omat({self.expr(stripped)})", self.indent))
        else:
            self.statements.append(Statement(f"print *, {self.expr(stripped)}", self.indent))

    def infer_kind(self, rhs: str) -> str:
        low = rhs.strip().lower()
        if re.match(r"^(mean|min|max|minval|maxval)\s*\(.+\)$", low, re.IGNORECASE):
            return "real"
        call = parse_simple_call(low)
        if call is not None:
            name, args = call
            if name in LA_SCALAR_FUNCTIONS:
                return "real"
            if name in {"col_sums", "col_means", "eig", "svd"}:
                return "real_vector"
            if name in LA_MATRIX_FUNCTIONS:
                return "real_matrix"
            if name == "diag" and args:
                sym = self.symbols.get(args[0].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_vector"
                return "real_matrix"
            if name in {"solve", "mldivide"} and len(args) >= 2:
                sym = self.symbols.get(args[1].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_matrix"
                return "real_vector"
        if re.match(r"^sum\s*\(.+\)$", low, re.IGNORECASE):
            args = split_args(low[low.find("(") + 1 : -1])
            if args:
                sym = self.symbols.get(args[0].lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_vector"
            return "real"
        if is_matrix_expr(low):
            return "real_matrix"
        if is_vector_expr(low):
            return "real_vector"
        m = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)$",
            rhs.strip(),
        )
        if m:
            left = self.symbols.get(m.group(1).lower())
            right = self.symbols.get(m.group(2).lower())
            if left is not None and right is not None:
                if left.kind == "real_matrix" and right.kind == "real_matrix":
                    return "real_matrix"
                if "real_matrix" in {left.kind, right.kind}:
                    return "real_vector"
        for name in IDENT_RE.findall(rhs):
            sym = self.symbols.get(name.lower())
            if sym is not None and sym.kind == "real_matrix" and rhs.strip().lower() == name.lower():
                return "real_matrix"
            if sym is not None and sym.kind == "real_vector":
                return "real_vector"
        return "real"

    def expr(self, text: str) -> str:
        out = text.strip()
        out = convert_vector_literals(out)
        out = convert_elementwise(out)
        out = self.convert_power(out)
        out = self.convert_matrix_multiply(out)
        out = self.convert_la_functions(out)
        out = self.convert_function_names(out)
        out = self.convert_rand(out)
        out = self.convert_zeros_ones(out)
        out = self.convert_equicor(out)
        out = self.convert_linspace(out)
        out = convert_numbers(out)
        return out

    def convert_power(self, text: str) -> str:
        if "^" not in text:
            return text
        for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*|\]|\))\s*\^", text):
            lhs = match.group(1)
            if lhs == "]":
                raise OmatError("^ is matrix power in MATLAB/Octave; use .^ for elementwise power")
            sym = self.symbols.get(lhs.lower())
            if sym is not None and sym.kind in {"real_vector", "real_matrix"}:
                raise OmatError("^ is matrix power in MATLAB/Octave; use .^ for elementwise power")
        return text.replace("^", "**")

    def convert_matrix_multiply(self, text: str) -> str:
        pattern = re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*(?:\([^()]*\))?)\s*\*\s*([A-Za-z_][A-Za-z0-9_]*(?:\([^()]*\))?)\b"
        )

        def base_name(value: str) -> str:
            return value.split("(", 1)[0].lower()

        def repl(match: re.Match[str]) -> str:
            left, right = match.groups()
            left_sym = self.symbols.get(base_name(left))
            right_sym = self.symbols.get(base_name(right))
            if (
                left_sym is not None
                and right_sym is not None
                and "real_matrix" in {left_sym.kind, right_sym.kind}
            ):
                return f"matmul({left}, {right})"
            return match.group(0)

        return pattern.sub(repl, text)

    def convert_la_functions(self, text: str) -> str:
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text):
            name = match.group(1).lower()
            if name in LA_FUNCTIONS:
                self.needs_la_mod = True
                self.la_names.add(name)
        return text

    def convert_function_names(self, text: str) -> str:
        out = text
        out = self.convert_sum(out)
        replacements = {
            "max": "maxval",
            "min": "minval",
        }
        for old, new in replacements.items():
            out = re.sub(rf"\b{old}\s*\(", f"{new}(", out, flags=re.IGNORECASE)
        return out

    def convert_sum(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if not args:
                raise OmatError("sum requires an argument")
            sym = self.symbols.get(args[0].strip().lower())
            if sym is None or sym.kind != "real_matrix":
                return match.group(0)
            if len(args) == 1:
                return f"sum({args[0]}, dim=1)"
            if len(args) == 2 and args[1].strip() in {"1", "2"}:
                return f"sum({args[0]}, dim={args[1].strip()})"
            raise OmatError("matrix sum currently supports sum(A), sum(A,1), and sum(A,2)")

        return re.sub(r"\bsum\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_rand(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"rand_omat(int({args[0]}))"
            if len(args) == 2:
                if args[1].strip() == "1":
                    return f"rand_omat(int({args[0]}))"
                return f"rand_omat2(int({args[0]}), int({args[1]}))"
            raise OmatError("rand currently supports rand(n), rand(n,1), and rand(m,n)")

        return re.sub(r"\brand\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_zeros_ones(self, text: str) -> str:
        def convert(name: str, value: str, current: str) -> str:
            def repl(match: re.Match[str]) -> str:
                args = split_args(match.group(1))
                if len(args) == 1:
                    return f"{value}_omat(int({args[0]}))"
                if len(args) == 2:
                    if args[1].strip() == "1":
                        return f"{value}_omat(int({args[0]}))"
                    return f"{value}_omat2(int({args[0]}), int({args[1]}))"
                raise OmatError(
                    f"{name} currently supports {name}(n), {name}(n,1), and {name}(m,n)"
                )

            return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, current, flags=re.IGNORECASE)

        out = convert("zeros", "zeros", text)
        out = convert("ones", "ones", out)
        return out

    def convert_equicor(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError("equicor requires two arguments: equicor(n, rho)")
            return f"equicor_omat(int({args[0]}), real({self.expr(args[1])}, real64))"

        return re.sub(r"\bequicor\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_linspace(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            self.needs_linstep = True
            args = split_args(match.group(1))
            if len(args) != 3:
                raise OmatError("linspace requires three arguments")
            return (
                f"linspace_omat(real({self.expr(args[0])}, real64), "
                f"real({self.expr(args[1])}, real64), int({self.expr(args[2])}))"
            )

        return re.sub(r"\blinspace\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def emit_fortran(self) -> str:
        lines: list[str] = []
        lines.append("program omat_main")
        lines.append("use, intrinsic :: iso_fortran_env, only: real64")
        if self.needs_la_mod:
            names = sorted(self.la_names)
            lines.append("use ofort_la_mod, only: " + ", ".join(names))
        lines.append("implicit none")
        for sym in self.symbols.values():
            if sym.kind == "integer":
                lines.append(f"integer :: {sym.name}")
            elif sym.kind == "real_vector":
                lines.append(f"real(real64), allocatable :: {sym.name}(:)")
            elif sym.kind == "real_matrix":
                lines.append(f"real(real64), allocatable :: {sym.name}(:,:)")
            else:
                lines.append(f"real(real64) :: {sym.name}")
        if self.symbols:
            lines.append("")
        for stmt in self.statements:
            lines.append("  " * stmt.indent + stmt.text)
        lines.append("contains")
        lines.extend(helper_source(self.needs_linstep))
        lines.append("end program omat_main")
        return "\n".join(lines) + "\n"


def strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "%" and not in_single and not in_double:
            return line[:i]
    return line


def parse_loop_spec(spec: str) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) == 2:
        return parts[0], parts[1], None
    if len(parts) == 3:
        return parts[0], parts[2], parts[1]
    raise OmatError("for loops must use start:stop or start:step:stop")


def parse_simple_call(text: str) -> tuple[str, list[str]] | None:
    stripped = text.strip()
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", stripped)
    if not m:
        return None
    name = m.group(1).lower()
    return name, split_args(m.group(2))


def is_vector_expr(text: str) -> bool:
    m = MATRIX_FUNC_RE.match(text)
    if m is not None:
        args = split_args(m.group(2))
        return len(args) == 1 or (len(args) == 2 and args[1].strip() == "1")
    return (
        (text.startswith("[") and ";" not in text)
        or re.match(r"^linspace\s*\(", text, re.IGNORECASE) is not None
    )


def is_matrix_expr(text: str) -> bool:
    if text.startswith("[") and ";" in text:
        return True
    if re.match(r"^equicor\s*\(", text, re.IGNORECASE) is not None:
        return True
    m = MATRIX_FUNC_RE.match(text)
    if m is not None:
        args = split_args(m.group(2))
        return len(args) == 2 and args[1].strip() != "1"
    return False


def convert_elementwise(text: str) -> str:
    return text.replace(".^", "**").replace(".*", "*").replace("./", "/")


def convert_function_names(text: str) -> str:
    replacements = {
        "max": "maxval",
        "min": "minval",
    }
    out = text
    for old, new in replacements.items():
        out = re.sub(rf"\b{old}\s*\(", f"{new}(", out, flags=re.IGNORECASE)
    return out


def convert_rand(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        args = split_args(match.group(1))
        if len(args) == 1:
            return f"rand_omat(int({args[0]}))"
        if len(args) == 2 and args[1].strip() == "1":
            return f"rand_omat(int({args[0]}))"
        raise OmatError("rand currently supports rand(n) and rand(n,1)")

    return re.sub(r"\brand\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)


def convert_zeros_ones(text: str) -> str:
    def convert(name: str, value: str, current: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"{value}_omat(int({args[0]}))"
            if len(args) == 2 and args[1].strip() == "1":
                return f"{value}_omat(int({args[0]}))"
            raise OmatError(f"{name} currently supports {name}(n) and {name}(n,1)")

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, current, flags=re.IGNORECASE)

    out = convert("zeros", "zeros", text)
    out = convert("ones", "ones", out)
    return out


def convert_vector_literals(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        if ";" not in body:
            items = [item for item in re.split(r"[\s,]+", body) if item]
            return "[" + ", ".join(items) + "]"
        rows = []
        ncols = None
        for raw_row in body.split(";"):
            row = [item for item in re.split(r"[\s,]+", raw_row.strip()) if item]
            if not row:
                raise OmatError("matrix literal contains an empty row")
            if ncols is None:
                ncols = len(row)
            elif len(row) != ncols:
                raise OmatError("matrix literal rows must have the same length")
            rows.append(row)
        flat = [item for row in rows for item in row]
        return (
            f"reshape([{', '.join(flat)}], [{len(rows)}, {ncols}], "
            "order=[2, 1])"
        )

    return re.sub(r"\[([^\[\]]+)\]", repl, text)


def convert_numbers(text: str) -> str:
    protected: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        key = f"__OMAT_PROTECT_{len(protected)}__"
        protected[key] = match.group(0)
        return key

    out = re.sub(r"'[^']*'|\"[^\"]*\"", protect, text)

    def repl(match: re.Match[str]) -> str:
        value = match.group(0).replace("D", "e").replace("d", "e")
        if "_real64" in value.lower():
            return value
        if any(ch in value for ch in ".eE"):
            return f"{value}_real64"
        return value

    out = NUMBER_RE.sub(repl, out)
    for key, value in protected.items():
        out = out.replace(key, value)
    return out


def split_args(text: str) -> list[str]:
    args: list[str] = []
    current = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def eval_repl_numeric_expr(text: str, scalar_values: dict[str, float]) -> float:
    source = text.strip().replace("D", "e").replace("d", "e").replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise OmatError("REPL rand size must be a scalar numeric expression") from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            value = scalar_values.get(node.id.lower())
            if value is None:
                raise OmatError(f"unknown scalar size variable '{node.id}'")
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
        raise OmatError("REPL rand size must be a scalar numeric expression")

    return visit(tree)


def parse_repl_size_arg(text: str, scalar_values: dict[str, float]) -> int:
    value = eval_repl_numeric_expr(text, scalar_values)
    if value >= 0 and float(value).is_integer():
        return int(value)
    raise OmatError("REPL rand size must evaluate to a non-negative integer")


def format_repl_real(value: float) -> str:
    return f"{value:.17g}"


def materialize_repl_rand(line: str, scalar_values: dict[str, float]) -> str:
    def repl(match: re.Match[str]) -> str:
        args = split_args(match.group(1))
        if len(args) == 1:
            n = parse_repl_size_arg(args[0], scalar_values)
            values = ", ".join(format_repl_real(random.random()) for _ in range(n))
            return f"[{values}]"
        elif len(args) == 2 and args[1].strip() == "1":
            n = parse_repl_size_arg(args[0], scalar_values)
            values = ", ".join(format_repl_real(random.random()) for _ in range(n))
            return f"[{values}]"
        elif len(args) == 2:
            nrow = parse_repl_size_arg(args[0], scalar_values)
            ncol = parse_repl_size_arg(args[1], scalar_values)
            rows = []
            for _ in range(nrow):
                row = " ".join(format_repl_real(random.random()) for _ in range(ncol))
                rows.append(row)
            return "[" + "; ".join(rows) + "]"
        else:
            raise OmatError("rand currently supports rand(n), rand(n,1), and rand(m,n)")

    return re.sub(r"\brand\s*\(([^()]*)\)", repl, line, flags=re.IGNORECASE)


def update_scalar_values(line: str, scalar_values: dict[str, float]) -> None:
    stripped = strip_comment(line).strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    m = ASSIGN_RE.match(stripped)
    if not m:
        return
    name, rhs = m.groups()
    rhs = rhs.strip()
    try:
        scalar_values[name.lower()] = eval_repl_numeric_expr(rhs, scalar_values)
    except OmatError:
        scalar_values.pop(name.lower(), None)


def helper_source(include_linspace: bool) -> list[str]:
    lines = [
        "function rand_omat(n) result(x)",
        "integer, intent(in) :: n",
        "real(real64), allocatable :: x(:)",
        "allocate(x(n))",
        "call random_number(x)",
        "end function rand_omat",
        "",
        "function rand_omat2(nrow, ncol) result(x)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: x(:,:)",
        "allocate(x(nrow, ncol))",
        "call random_number(x)",
        "end function rand_omat2",
        "",
        "function zeros_omat(n) result(x)",
        "integer, intent(in) :: n",
        "real(real64), allocatable :: x(:)",
        "allocate(x(n))",
        "x = 0.0_real64",
        "end function zeros_omat",
        "",
        "function zeros_omat2(nrow, ncol) result(x)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: x(:,:)",
        "allocate(x(nrow, ncol))",
        "x = 0.0_real64",
        "end function zeros_omat2",
        "",
        "function ones_omat(n) result(x)",
        "integer, intent(in) :: n",
        "real(real64), allocatable :: x(:)",
        "allocate(x(n))",
        "x = 1.0_real64",
        "end function ones_omat",
        "",
        "function ones_omat2(nrow, ncol) result(x)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: x(:,:)",
        "allocate(x(nrow, ncol))",
        "x = 1.0_real64",
        "end function ones_omat2",
        "",
        "function equicor_omat(n, rho) result(x)",
        "integer, intent(in) :: n",
        "real(real64), intent(in) :: rho",
        "real(real64), allocatable :: x(:,:)",
        "integer :: i",
        "allocate(x(n, n))",
        "x = rho",
        "do i = 1, n",
        "  x(i, i) = 1.0_real64",
        "end do",
        "end function equicor_omat",
        "",
        "subroutine print_matrix_omat(x)",
        "real(real64), intent(in) :: x(:,:)",
        "integer :: i",
        "do i = 1, size(x, 1)",
        "  print *, x(i, :)",
        "end do",
        "end subroutine print_matrix_omat",
        "",
        "real(real64) function mean(x)",
        "real(real64), intent(in) :: x(:)",
        "mean = sum(x) / real(size(x), real64)",
        "end function mean",
    ]
    if include_linspace:
        lines.extend(
            [
                "",
                "function linspace_omat(a, b, n) result(x)",
                "real(real64), intent(in) :: a, b",
                "integer, intent(in) :: n",
                "real(real64), allocatable :: x(:)",
                "integer :: i",
                "allocate(x(n))",
                "if (n <= 1) then",
                "  if (n == 1) x(1) = a",
                "else",
                "  do i = 1, n",
                "    x(i) = a + (b - a) * real(i - 1, real64) / real(n - 1, real64)",
                "  end do",
                "end if",
                "end function linspace_omat",
            ]
        )
    return lines


def translate_source(source: str) -> str:
    return Translator().translate(source)


def validate_partial_source(source: str) -> None:
    translator = Translator()
    for line_no, raw in enumerate(source.splitlines(), start=1):
        translator.add_line(raw, line_no)


def compile_and_run_capture(
    generated: str,
    compiler_name: str,
    emit_fortran: str | None = None,
    keep_path: Path | None = None,
) -> ExecResult:
    compiler = shutil.which(compiler_name)
    if compiler is None:
        return ExecResult(2, "", "omat: gfortran not found; use --emit-fortran or --no-run\n")

    with tempfile.TemporaryDirectory(prefix="omat_") as tmp:
        tmpdir = Path(tmp)
        f90 = Path(emit_fortran) if emit_fortran else tmpdir / "omat_main.f90"
        exe = tmpdir / ("omat.exe" if sys.platform.startswith("win") else "omat.out")
        if not emit_fortran:
            f90.write_text(generated, encoding="utf-8")
        build = subprocess.run([compiler, str(f90), "-o", str(exe)], text=True, capture_output=True)
        if build.returncode != 0:
            return ExecResult(build.returncode, build.stdout, build.stderr)
        result = subprocess.run([str(exe)], text=True, capture_output=True)
        if keep_path is not None and not emit_fortran:
            keep_path.write_text(generated, encoding="utf-8")
            result.stderr += f"omat: kept generated Fortran in {keep_path}\n"
        return ExecResult(result.returncode, result.stdout, result.stderr)


def compile_and_run(
    generated: str,
    compiler_name: str,
    emit_fortran: str | None = None,
    keep_path: Path | None = None,
) -> int:
    result = compile_and_run_capture(generated, compiler_name, emit_fortran, keep_path)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_with_ofort(
    generated: str,
    ofort_path: str,
    keep_path: Path | None = None,
) -> int:
    result = run_with_ofort_capture(generated, ofort_path)
    if keep_path is not None:
        keep_path.write_text(generated, encoding="utf-8")
        result.stderr += f"omat: kept generated Fortran in {keep_path}\n"
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_with_ofort_capture(generated: str, ofort_path: str) -> ExecResult:
    ofort = Path(ofort_path)
    if not ofort.exists():
        found = shutil.which(ofort_path)
        if found is None:
            return ExecResult(2, "", f"omat: ofort not found: {ofort_path}\n")
        ofort = Path(found)
    with tempfile.TemporaryDirectory(prefix="omat_") as tmp:
        source = Path(tmp) / "omat_main.f90"
        source.write_text(generated, encoding="utf-8")
        result = subprocess.run(
            [str(ofort), "--no-warn-unused", str(source)],
            text=True,
            capture_output=True,
        )
        return ExecResult(result.returncode, result.stdout, result.stderr)


def line_opens_block(line: str) -> bool:
    stripped = strip_comment(line).strip()
    return FOR_RE.match(stripped) is not None


def line_closes_block(line: str) -> bool:
    return strip_comment(line).strip().lower() == "end"


def suppress_repl_output(line: str) -> str:
    stripped = strip_comment(line).strip()
    if not stripped or stripped.endswith(";") or line_opens_block(line) or line_closes_block(line):
        return line
    return line.rstrip() + ";"


def summarize_repl_assignment(line: str) -> str | None:
    stripped = strip_comment(line).strip()
    if stripped.endswith(";"):
        return None
    m = ASSIGN_RE.match(stripped)
    if not m:
        return None
    _, rhs = m.groups()
    rhs = rhs.strip()
    if not (rhs.startswith("[") and rhs.endswith("]")):
        return None
    body = rhs[1:-1].strip()
    if not body:
        return None
    if ";" not in body:
        values = [item for item in re.split(r"[\s,]+", body) if item]
        if len(values) <= 12:
            return None
        shown = values[:6] + ["..."] + values[-3:]
        return " ".join(shown) + f"  ({len(values)} values)\n"

    rows = [[item for item in re.split(r"[\s,]+", row.strip()) if item] for row in body.split(";")]
    rows = [row for row in rows if row]
    if not rows:
        return None
    nrow = len(rows)
    ncol = max(len(row) for row in rows)
    if nrow <= 6 and ncol <= 8:
        return None
    shown_rows = []
    for row in rows[:3]:
        if len(row) > 6:
            shown_rows.append(" ".join(row[:6] + ["..."]))
        else:
            shown_rows.append(" ".join(row))
    if nrow > 3:
        shown_rows.append("...")
    shown_rows.append(f"({nrow}x{ncol} matrix)")
    return "\n".join(shown_rows) + "\n"


def run_repl_source(source_lines: list[str], ofort: str, summary: str | None = None) -> str | None:
    try:
        generated = translate_source("\n".join(source_lines))
    except OmatError as exc:
        print(f"omat: {exc}", file=sys.stderr)
        return None
    result = run_with_ofort_capture(generated, ofort)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        return None
    if summary is not None:
        print(summary, end="")
    else:
        print(result.stdout, end="")
    return result.stdout


def run_repl_buffer(buffer: list[str], ofort: str) -> str | None:
    return run_repl_source(buffer, ofort)


def run_repl_candidate(buffer: list[str], line: str, ofort: str) -> str | None:
    source_lines = [suppress_repl_output(prior) for prior in buffer]
    summary = summarize_repl_assignment(line)
    source_lines.append(suppress_repl_output(line) if summary is not None else line)
    return run_repl_source(source_lines, ofort, summary)


def report_omat_error(exc: OmatError) -> None:
    print(f"omat: {exc}", file=sys.stderr)


def repl(ofort: str) -> int:
    buffer: list[str] = []
    scalar_values: dict[str, float] = {}
    block_depth = 0
    print("omat interactive mode")
    print("Commands: run, fortran, list, clear, quit")
    while True:
        try:
            line = input("omat> ")
        except EOFError:
            print()
            return 0
        command = line.strip().lower()
        if command in {"quit", "q", "exit"}:
            return 0
        if command == "clear":
            buffer.clear()
            scalar_values.clear()
            block_depth = 0
            continue
        if command == "list":
            for i, source_line in enumerate(buffer, start=1):
                print(f"{i:4d}  {source_line}")
            continue
        if command == "fortran":
            try:
                print(translate_source("\n".join(buffer)), end="")
            except OmatError as exc:
                print(f"omat: {exc}", file=sys.stderr)
            continue
        if command in {"run", "."}:
            run_repl_buffer(buffer, ofort)
            continue
        try:
            materialized_line = materialize_repl_rand(line, scalar_values)
        except OmatError as exc:
            report_omat_error(exc)
            continue
        candidate = [*buffer, materialized_line]
        if line_opens_block(materialized_line):
            try:
                validate_partial_source("\n".join(candidate))
            except OmatError as exc:
                report_omat_error(exc)
                continue
            buffer = candidate
            update_scalar_values(materialized_line, scalar_values)
            block_depth += 1
            continue
        if line_closes_block(materialized_line) and block_depth > 0:
            new_block_depth = block_depth - 1
        else:
            new_block_depth = block_depth
        if new_block_depth > 0:
            try:
                validate_partial_source("\n".join(candidate))
            except OmatError as exc:
                report_omat_error(exc)
                continue
            buffer = candidate
            update_scalar_values(materialized_line, scalar_values)
            block_depth = new_block_depth
            continue
        stdout = run_repl_candidate(buffer, materialized_line, ofort)
        if stdout is not None:
            buffer = candidate
            update_scalar_values(materialized_line, scalar_values)
            block_depth = new_block_depth


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Translate a small MATLAB/Octave-like numerical subset to Fortran and optionally run it."
    )
    parser.add_argument("source", nargs="?", help="MATLAB/Octave-like source file")
    parser.add_argument("--emit-fortran", metavar="FILE", help="write generated Fortran to FILE")
    parser.add_argument("--no-run", action="store_true", help="translate only; do not compile or run")
    parser.add_argument("--gfortran", default="gfortran", help="gfortran command (default: gfortran)")
    parser.add_argument(
        "--ofort",
        default=str(DEFAULT_OFORT),
        help=f"ofort command for REPL execution (default: {DEFAULT_OFORT})",
    )
    parser.add_argument("--keep", action="store_true", help="keep generated temporary files")
    args = parser.parse_args(argv)

    if args.source is None:
        if args.emit_fortran or args.no_run or args.keep:
            print("omat: source file is required with --emit-fortran, --no-run, or --keep", file=sys.stderr)
            return 2
        return repl(args.ofort)

    source_path = Path(args.source)
    try:
        generated = translate_source(source_path.read_text(encoding="utf-8"))
    except OmatError as exc:
        print(f"omat: {exc}", file=sys.stderr)
        return 1

    if args.emit_fortran:
        Path(args.emit_fortran).write_text(generated, encoding="utf-8")
    if args.no_run:
        if not args.emit_fortran:
            print(generated, end="")
        return 0

    keep_path = source_path.with_suffix(".f90") if args.keep else None
    if "use ofort_la_mod" in generated:
        return run_with_ofort(generated, args.ofort, keep_path)
    return compile_and_run(generated, args.gfortran, args.emit_fortran, keep_path)


if __name__ == "__main__":
    raise SystemExit(run())
