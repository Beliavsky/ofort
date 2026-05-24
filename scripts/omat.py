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
DEFAULT_MATERIALIZE_RAND_LIMIT = 10
DEFAULT_SESSION_FORTRAN = "omat_session.f90"
DEFAULT_GENERIC_SESSION_FORTRAN = "generic_session.f90"
DEFAULT_SESSION_SOURCE = "omat_session.m"

IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d+\.\d*|\.\d+|\d+)(?:[eEdD][+-]?\d+)?(?![A-Za-z0-9_])"
)
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)


BUILTINS = {
    "abs",
    "acos",
    "all",
    "any",
    "asin",
    "atan",
    "cos",
    "equicor",
    "exp",
    "log",
    "mad",
    "maxval",
    "mean",
    "median",
    "minval",
    "corr",
    "corrcoef",
    "cov",
    "cumsum",
    "diff",
    "find",
    "iqr",
    "isfinite",
    "isinf",
    "isnan",
    "kurtosis",
    "length",
    "movmean",
    "numel",
    "prctile",
    "quantile",
    "reshape",
    "rms",
    "sqrt",
    "std",
    "skewness",
    "sin",
    "size",
    "sum",
    "sort",
    "tan",
    "var",
    "zscore",
}

MATRIX_FUNC_RE = re.compile(r"^(rand|zeros|ones)\s*\((.*)\)$", re.IGNORECASE)
STAT_SCALAR_FUNCTIONS = {
    "mean", "std", "var", "median", "skewness", "kurtosis", "rms", "mad",
    "quantile", "prctile", "iqr", "corr"
}
STAT_VECTOR_FUNCTIONS = {"cumsum", "zscore", "movmean"}
STAT_MATRIX_FUNCTIONS = {"cov", "corrcoef"}
LA_SCALAR_FUNCTIONS = {"trace", "det", "cond", "norm", "rank", "is_square", "is_diagonal", "is_symmetric", "is_invertible"}
LA_VECTOR_FUNCTIONS = {"eig", "svd"}
LA_MATRIX_FUNCTIONS = {"eye", "triu", "tril", "kron", "inv", "qr", "lu", "pinv", "chol", "outer_product", "transpose2", "matmul2", "crossprod", "tcrossprod"}
LA_FUNCTIONS = LA_SCALAR_FUNCTIONS | LA_VECTOR_FUNCTIONS | LA_MATRIX_FUNCTIONS | {"diag", "solve", "mldivide", "col_sums", "col_means"}
RANDOM_DIST_PARAM_COUNTS = {
    "randn": 0,
    "normrnd": 2,
    "unifrnd": 2,
    "exprnd": 1,
    "lognrnd": 2,
    "gamrnd": 2,
    "poissrnd": 1,
    "binornd": 2,
    "trnd": 1,
    "laprnd": 2,
    "sechrnd": 2,
    "logisticrnd": 2,
}

MATLAB_BUILTINS_NOT_IMPLEMENTED = {
    "accumarray",
    "bar",
    "bsxfun",
    "cell",
    "cellfun",
    "class",
    "conv",
    "conv2",
    "datenum",
    "datestr",
    "exist",
    "fft",
    "fft2",
    "filter",
    "fminsearch",
    "fplot",
    "fzero",
    "grid",
    "hist",
    "histogram",
    "ifft",
    "ifft2",
    "imagesc",
    "interp1",
    "interp2",
    "legend",
    "meshgrid",
    "ode45",
    "plot",
    "polyfit",
    "polyval",
    "readmatrix",
    "readtable",
    "roots",
    "scatter",
    "sortrows",
    "sparse",
    "sprintf",
    "string",
    "struct",
    "table",
    "title",
    "writematrix",
    "writetable",
    "xlabel",
    "ylabel",
}

PURE_HELPERS = {
    "zeros_omat",
    "zeros_omat2",
    "ones_omat",
    "ones_omat2",
    "equicor_omat",
    "mean",
    "mean_vec_omat",
    "mean_mat_omat",
    "var_vec_omat",
    "var_mat_omat",
    "std_vec_omat",
    "std_mat_omat",
    "rms_vec_omat",
    "rms_mat_omat",
    "median_vec_omat",
    "median_mat_omat",
    "mad_vec_omat",
    "mad_mat_omat",
    "quantile_vec_omat",
    "quantile_mat_omat",
    "prctile_vec_omat",
    "prctile_mat_omat",
    "iqr_vec_omat",
    "iqr_mat_omat",
    "skewness_vec_omat",
    "skewness_mat_omat",
    "kurtosis_vec_omat",
    "kurtosis_mat_omat",
    "cumsum_vec_omat",
    "cumsum_mat_omat",
    "zscore_vec_omat",
    "zscore_mat_omat",
    "movmean_vec_omat",
    "movmean_mat_omat",
    "cov_omat",
    "corrcoef_omat",
    "linspace_omat",
    "diff_vec_omat",
    "sort_vec_omat",
    "find_vec_omat",
    "isnan_vec_omat",
    "isfinite_vec_omat",
    "isinf_vec_omat",
    "any_vec_omat",
    "all_vec_omat",
}


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
    def __init__(self, generic: bool = False) -> None:
        self.symbols: dict[str, Symbol] = {}
        self.statements: list[Statement] = []
        self.indent = 0
        self.needs_linstep = False
        self.needs_la_mod = False
        self.la_names: set[str] = set()
        self.needs_random_mod = False
        self.random_names: set[str] = set()
        self.random_specific_names: set[str] = set()
        self.generic = generic

    def translate(self, source: str) -> str:
        for line_no, raw in enumerate(source.splitlines(), start=1):
            self.add_line(raw, line_no)
        if self.indent != 0:
            raise OmatError("unterminated block: missing end")
        if self.generic:
            blocked = sorted(self.la_names)
            if blocked:
                names = ", ".join(blocked)
                raise OmatError(f"generic Fortran cannot use ofort-specific module procedures yet: {names}")
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
        if self.is_logical_expr(rhs):
            return self.logical_expr_kind(rhs)
        if re.match(r"^(min|max|minval|maxval)\s*\(.+\)$", low, re.IGNORECASE):
            return "real"
        if is_flatten_expr(low):
            return "real_vector"
        call = parse_simple_call(low)
        if call is not None:
            name, args = call
            if name in {"length", "numel"}:
                return "integer"
            if name in {"any", "all"}:
                return "logical"
            if name == "find":
                return "integer_vector"
            if name in {"isnan", "isfinite", "isinf"}:
                return "logical_vector"
            if name in {"diff", "sort"}:
                return "real_vector"
            if name == "reshape":
                if len(args) == 3:
                    return "real_matrix"
                if len(args) == 2:
                    shape_rank = shape_literal_rank(args[1])
                    if shape_rank == 2:
                        return "real_matrix"
                    return "real_vector"
            if name in STAT_SCALAR_FUNCTIONS:
                if name != "corr" and args:
                    sym = self.symbols.get(args[0].strip().lower())
                    if sym is not None and sym.kind == "real_matrix":
                        return "real_vector"
                return "real"
            if name in STAT_VECTOR_FUNCTIONS:
                if args:
                    sym = self.symbols.get(args[0].strip().lower())
                    if sym is not None and sym.kind == "real_matrix":
                        return "real_matrix"
                return "real_vector"
            if name in STAT_MATRIX_FUNCTIONS:
                return "real_matrix"
            if name in RANDOM_DIST_PARAM_COUNTS:
                n_size_args = len(args) - RANDOM_DIST_PARAM_COUNTS[name]
                if n_size_args <= 0:
                    return "real"
                if n_size_args == 1:
                    return "real_vector"
                return "real_matrix"
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

    def is_logical_expr(self, rhs: str) -> bool:
        return re.search(r"(==|~=|<=|>=|<|>)", rhs) is not None

    def logical_expr_kind(self, rhs: str) -> str:
        for name in IDENT_RE.findall(rhs):
            sym = self.symbols.get(name.lower())
            if sym is not None and sym.kind == "real_matrix":
                return "logical_matrix"
            if sym is not None and sym.kind in {"real_vector", "integer_vector", "logical_vector"}:
                return "logical_vector"
        return "logical"

    def expr(self, text: str) -> str:
        out = text.strip()
        self.reject_unimplemented_matlab_functions(out)
        out = self.convert_matlab_reshape(out)
        out = self.convert_colon_flatten(out)
        out = convert_vector_literals(out)
        out = convert_elementwise(out)
        out = self.convert_power(out)
        out = self.convert_matrix_multiply(out)
        out = self.convert_la_functions(out)
        out = self.convert_random_dist_functions(out)
        out = self.convert_basic_array_functions(out)
        out = self.convert_stats_functions(out)
        out = self.convert_function_names(out)
        out = self.convert_rand(out)
        out = self.convert_zeros_ones(out)
        out = self.convert_equicor(out)
        out = self.convert_linspace(out)
        out = convert_numbers(out)
        return out

    def convert_basic_array_functions(self, text: str) -> str:
        out = text
        out = self.convert_length_numel(out)
        out = self.convert_one_arg_kind_function(out, "diff", "diff_vec_omat")
        out = self.convert_one_arg_kind_function(out, "sort", "sort_vec_omat")
        out = self.convert_one_arg_kind_function(out, "find", "find_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isnan", "isnan_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isfinite", "isfinite_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isinf", "isinf_vec_omat")
        out = self.convert_one_arg_kind_function(out, "any", "any_vec_omat")
        out = self.convert_one_arg_kind_function(out, "all", "all_vec_omat")
        return out

    def convert_length_numel(self, text: str) -> str:
        def repl_length(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError("length currently supports one argument")
            arg = args[0].strip()
            expr = self.expr(arg)
            sym = self.symbols.get(arg.lower())
            if sym is not None and sym.kind.endswith("_matrix"):
                return f"max(size({expr}, 1), size({expr}, 2))"
            if sym is not None and sym.kind.endswith("_vector"):
                return f"size({expr})"
            return "1"

        def repl_numel(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError("numel currently supports one argument")
            arg = args[0].strip()
            expr = self.expr(arg)
            sym = self.symbols.get(arg.lower())
            if sym is not None and (sym.kind.endswith("_matrix") or sym.kind.endswith("_vector")):
                return f"size({expr})"
            return "1"

        out = re.sub(r"\blength\s*\(([^()]*)\)", repl_length, text, flags=re.IGNORECASE)
        out = re.sub(r"\bnumel\s*\(([^()]*)\)", repl_numel, out, flags=re.IGNORECASE)
        return out

    def convert_one_arg_kind_function(self, text: str, name: str, helper: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one argument")
            return f"{helper}({self.expr(args[0])})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def reject_unimplemented_matlab_functions(self, text: str) -> None:
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text):
            name = match.group(1).lower()
            if name in MATLAB_BUILTINS_NOT_IMPLEMENTED:
                raise OmatError(f"MATLAB built-in '{name}' is not implemented yet")

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

    def convert_random_dist_functions(self, text: str) -> str:
        out = text
        for name, nparam in RANDOM_DIST_PARAM_COUNTS.items():
            def repl(match: re.Match[str], name: str = name, nparam: int = nparam) -> str:
                args = split_args(match.group(1))
                if len(args) < nparam:
                    raise OmatError(f"{name} requires at least {nparam} parameter arguments")
                self.needs_random_mod = True
                self.random_names.add(name)
                self.random_specific_names.add(random_specific_name(name, len(args) - nparam))
                params = [
                    f"real({convert_numbers(convert_elementwise(arg.strip()))}, real64)"
                    for arg in args[:nparam]
                ]
                sizes = [self.integer_arg(arg) for arg in args[nparam:]]
                return f"{name}({', '.join(params + sizes)})"

            out = re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, out, flags=re.IGNORECASE)
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", out):
            name = match.group(1).lower()
            if name in RANDOM_DIST_PARAM_COUNTS:
                self.needs_random_mod = True
                self.random_names.add(name)
                if not any(specific.startswith(f"{name}_") for specific in self.random_specific_names):
                    self.random_specific_names.update(random_specific_names_for_family(name))
        return out

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

    def convert_stats_functions(self, text: str) -> str:
        out = text
        for name in ["mean", "std", "var", "median", "skewness", "kurtosis", "rms", "mad", "iqr", "cumsum", "zscore"]:
            out = self.convert_one_stats_function(out, name)
        out = self.convert_quantile_function(out, "quantile", "quantile")
        out = self.convert_quantile_function(out, "prctile", "prctile")
        out = self.convert_movmean_function(out)
        out = self.convert_binary_vector_function(out, "corr", "corr_omat")
        out = self.convert_matrix_stats_function(out, "cov", "cov_omat")
        out = self.convert_matrix_stats_function(out, "corrcoef", "corrcoef_omat")
        return out

    def convert_one_stats_function(self, text: str, name: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one argument")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            suffix = "mat" if sym is not None and sym.kind == "real_matrix" else "vec"
            helper = f"{name}_{suffix}_omat"
            return f"{helper}({self.expr(arg)})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_quantile_function(self, text: str, name: str, helper_base: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError(f"{name} currently supports two arguments")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            suffix = "mat" if sym is not None and sym.kind == "real_matrix" else "vec"
            return f"{helper_base}_{suffix}_omat({self.expr(arg)}, real({self.expr(args[1])}, real64))"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_movmean_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError("movmean currently supports movmean(x,k)")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            suffix = "mat" if sym is not None and sym.kind == "real_matrix" else "vec"
            return f"movmean_{suffix}_omat({self.expr(arg)}, {self.integer_arg(args[1])})"

        return re.sub(r"\bmovmean\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_binary_vector_function(self, text: str, name: str, helper: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError(f"{name} currently supports two vector arguments")
            return f"{helper}({self.expr(args[0])}, {self.expr(args[1])})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_matrix_stats_function(self, text: str, name: str, helper: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one matrix argument")
            return f"{helper}({self.expr(args[0])})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_matlab_reshape(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            source = self.expr(args[0]) if args else ""
            source_kind = self.expr_kind(args[0]) if args else "real_vector"
            if len(args) == 3:
                helper = (
                    "reshape_mat_from_mat_omat"
                    if source_kind == "real_matrix"
                    else "reshape_mat_from_vec_omat"
                )
                return (
                    f"{helper}({source}, "
                    f"{self.integer_arg(args[1])}, {self.integer_arg(args[2])})"
                )
            if len(args) == 2:
                shape_args = shape_literal_args(args[1])
                if shape_args is None:
                    raise OmatError("reshape shape currently must be [n] or [m,n]")
                if len(shape_args) == 1:
                    helper = (
                        "reshape_vec_from_mat_omat"
                        if source_kind == "real_matrix"
                        else "reshape_vec_from_vec_omat"
                    )
                    return f"{helper}({source}, {self.integer_arg(shape_args[0])})"
                if len(shape_args) == 2:
                    helper = (
                        "reshape_mat_from_mat_omat"
                        if source_kind == "real_matrix"
                        else "reshape_mat_from_vec_omat"
                    )
                    return (
                        f"{helper}({source}, "
                        f"{self.integer_arg(shape_args[0])}, {self.integer_arg(shape_args[1])})"
                    )
                raise OmatError("reshape shape currently must be [n] or [m,n]")
            raise OmatError("reshape currently supports reshape(x,m,n) and reshape(x,[...])")

        return re.sub(r"\breshape\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_colon_flatten(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            sym = self.symbols.get(name.lower())
            if sym is not None and sym.kind == "real_matrix":
                return f"reshape_vec_from_mat_omat({name}, size({name}))"
            return f"reshape_vec_from_vec_omat({name}, size({name}))"

        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*:\s*\)", repl, text)

    def expr_kind(self, text: str) -> str:
        low = text.strip().lower()
        sym = self.symbols.get(low)
        if sym is not None:
            return sym.kind
        if is_matrix_expr(low):
            return "real_matrix"
        if is_vector_expr(low):
            return "real_vector"
        return "real_vector"

    def convert_rand(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"rand_omat({self.integer_arg(args[0])})"
            if len(args) == 2:
                if args[1].strip() == "1":
                    return f"rand_omat({self.integer_arg(args[0])})"
                return f"rand_omat2({self.integer_arg(args[0])}, {self.integer_arg(args[1])})"
            raise OmatError("rand currently supports rand(n), rand(n,1), and rand(m,n)")

        return re.sub(r"\brand\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_zeros_ones(self, text: str) -> str:
        def convert(name: str, value: str, current: str) -> str:
            def repl(match: re.Match[str]) -> str:
                args = split_args(match.group(1))
                if len(args) == 1:
                    return f"{value}_omat({self.integer_arg(args[0])})"
                if len(args) == 2:
                    if args[1].strip() == "1":
                        return f"{value}_omat({self.integer_arg(args[0])})"
                    return f"{value}_omat2({self.integer_arg(args[0])}, {self.integer_arg(args[1])})"
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
            return f"equicor_omat({self.integer_arg(args[0])}, real({self.expr(args[1])}, real64))"

        return re.sub(r"\bequicor\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_linspace(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            self.needs_linstep = True
            args = split_args(match.group(1))
            if len(args) != 3:
                raise OmatError("linspace requires three arguments")
            return (
                f"linspace_omat(real({self.expr(args[0])}, real64), "
                f"real({self.expr(args[1])}, real64), {self.integer_arg(args[2])})"
            )

        return re.sub(r"\blinspace\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def integer_arg(self, text: str) -> str:
        expr = self.expr(text)
        if is_integer_expr(expr, self.symbols):
            return expr
        return f"int({expr})"

    def emit_fortran(self) -> str:
        kind_alias = self.real64_alias()
        body_lines: list[str] = []
        for stmt in self.statements:
            body_lines.append("  " * stmt.indent + stmt.text)
        helper_lines: list[str] = []
        helper_public_names: list[str] = []
        if any(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*_omat[0-9]*\s*\(", line) for line in body_lines):
            helper_lines = helper_source(self.needs_linstep, body_lines)
            helper_public_names = [name for name, _ in split_helper_blocks(helper_lines)]
        module_public_names = [kind_alias, *helper_public_names]

        lines: list[str] = []
        if self.generic and self.random_names:
            lines.extend(generic_random_module_source(sorted(self.random_names), self.random_specific_names))
            lines.append("")
        lines.append("module m_mod")
        lines.append(f"use, intrinsic :: iso_fortran_env, only: {kind_alias} => real64")
        lines.append("implicit none")
        lines.append("private")
        lines.append("public :: " + ", ".join(module_public_names))
        if helper_lines:
            lines.append("contains")
            lines.extend(helper_lines)
        lines.append("end module m_mod")
        lines.append("")
        lines.append("program omat_main")
        lines.append("use m_mod, only: " + ", ".join(module_public_names))
        if self.needs_la_mod:
            names = sorted(self.la_names)
            lines.append("use ofort_la_mod, only: " + ", ".join(names))
        if self.needs_random_mod:
            names = sorted(self.random_names)
            module_name = "random_mod" if self.generic else "ofort_random_mod"
            lines.append(f"use {module_name}, only: " + ", ".join(names))
        lines.append("implicit none")
        for sym in self.symbols.values():
            if sym.kind == "integer":
                lines.append(f"integer :: {sym.name}")
            elif sym.kind == "logical":
                lines.append(f"logical :: {sym.name}")
            elif sym.kind == "integer_vector":
                lines.append(f"integer, allocatable :: {sym.name}(:)")
            elif sym.kind == "logical_vector":
                lines.append(f"logical, allocatable :: {sym.name}(:)")
            elif sym.kind == "logical_matrix":
                lines.append(f"logical, allocatable :: {sym.name}(:,:)")
            elif sym.kind == "real_vector":
                lines.append(f"real(real64), allocatable :: {sym.name}(:)")
            elif sym.kind == "real_matrix":
                lines.append(f"real(real64), allocatable :: {sym.name}(:,:)")
            else:
                lines.append(f"real(real64) :: {sym.name}")
        if self.symbols:
            lines.append("")
        lines.extend(body_lines)
        lines.append("end program omat_main")
        return self.apply_real64_alias(lines, kind_alias) + "\n"

    def real64_alias(self) -> str:
        used = set(self.symbols)
        alias = "dp"
        while alias.lower() in used:
            alias += "_"
        return alias

    def apply_real64_alias(self, lines: list[str], alias: str) -> str:
        out: list[str] = []
        for line in lines:
            if "iso_fortran_env" in line:
                out.append(line)
                continue
            line = re.sub(r"_real64\b", f"_{alias}", line)
            line = re.sub(r"\breal64\b", alias, line)
            out.append(line)
        return clean_emitted_helper_names("\n".join(out))


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
    if is_flatten_expr(text):
        return True
    m = MATRIX_FUNC_RE.match(text)
    if m is not None:
        args = split_args(m.group(2))
        return len(args) == 1 or (len(args) == 2 and args[1].strip() == "1")
    return (
        (text.startswith("[") and ";" not in text)
        or re.match(r"^linspace\s*\(", text, re.IGNORECASE) is not None
    )


def is_matrix_expr(text: str) -> bool:
    call = parse_simple_call(text)
    if call is not None:
        name, args = call
        if name == "reshape" and len(args) == 3:
            return True
        if name == "reshape" and len(args) == 2 and shape_literal_rank(args[1]) == 2:
            return True
    if text.startswith("[") and ";" in text:
        return True
    if re.match(r"^equicor\s*\(", text, re.IGNORECASE) is not None:
        return True
    m = MATRIX_FUNC_RE.match(text)
    if m is not None:
        args = split_args(m.group(2))
        return len(args) == 2 and args[1].strip() != "1"
    return False


def is_flatten_expr(text: str) -> bool:
    return re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(\s*:\s*\)$", text) is not None


def shape_literal_rank(text: str) -> int | None:
    args = shape_literal_args(text)
    return None if args is None else len(args)


def shape_literal_args(text: str) -> list[str] | None:
    stripped = text.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    body = stripped[1:-1].strip()
    if not body:
        return None
    return split_args(body)


def is_integer_expr(text: str, symbols: dict[str, Symbol]) -> bool:
    source = text.strip().replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return False

    def visit(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return isinstance(node.value, int) and not isinstance(node.value, bool)
        if isinstance(node, ast.Name):
            sym = symbols.get(node.id.lower())
            return sym is not None and sym.kind == "integer"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                return False
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Pow)):
                return False
            return visit(node.left) and visit(node.right)
        return False

    return visit(tree)


def clean_emitted_helper_names(source: str) -> str:
    return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)_omat([0-9]*)\b", r"\1\2", source)


def convert_elementwise(text: str) -> str:
    return text.replace(".^", "**").replace(".*", "*").replace("./", "/").replace("~=", "/=")


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
            items = split_matlab_literal_row(body)
            return "[" + ", ".join(items) + "]"
        rows = []
        ncols = None
        for raw_row in body.split(";"):
            row = split_matlab_literal_row(raw_row.strip())
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


def split_matlab_literal_row(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and (ch == "," or ch.isspace()):
            if current:
                items.append("".join(current).strip())
                current = []
        else:
            current.append(ch)
    if current:
        items.append("".join(current).strip())
    return [item for item in items if item]


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


def normalize_repl_rand_size_expr(text: str) -> str:
    return text.strip().replace("^", "**")


def materialize_repl_rand(
    line: str,
    scalar_values: dict[str, float],
    materialize_limit: int = DEFAULT_MATERIALIZE_RAND_LIMIT,
) -> str:
    def repl(match: re.Match[str]) -> str:
        args = split_args(match.group(1))
        if len(args) == 1:
            n = parse_repl_size_arg(args[0], scalar_values)
            if n > materialize_limit:
                return f"rand({normalize_repl_rand_size_expr(args[0])})"
            values = ", ".join(format_repl_real(random.random()) for _ in range(n))
            return f"[{values}]"
        elif len(args) == 2 and args[1].strip() == "1":
            n = parse_repl_size_arg(args[0], scalar_values)
            if n > materialize_limit:
                return f"rand({normalize_repl_rand_size_expr(args[0])}, 1)"
            values = ", ".join(format_repl_real(random.random()) for _ in range(n))
            return f"[{values}]"
        elif len(args) == 2:
            nrow = parse_repl_size_arg(args[0], scalar_values)
            ncol = parse_repl_size_arg(args[1], scalar_values)
            if nrow * ncol > materialize_limit:
                return (
                    f"rand({normalize_repl_rand_size_expr(args[0])}, "
                    f"{normalize_repl_rand_size_expr(args[1])})"
                )
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


def random_specific_name(name: str, n_size_args: int) -> str:
    if n_size_args <= 0:
        return f"{name}_scalar"
    if n_size_args == 1:
        return f"{name}_vec"
    return f"{name}_mat"


def random_specific_names_for_family(name: str) -> set[str]:
    return {f"{name}_scalar", f"{name}_vec", f"{name}_mat"}


def generic_random_module_source(public_names: list[str], specific_names: set[str] | None = None) -> list[str]:
    public = ", ".join(public_names)
    lines = [
        "module random_mod",
        "use, intrinsic :: iso_fortran_env, only: dp => real64",
        "implicit none",
        "private",
        f"public :: {public}",
        "real(dp), parameter :: pi = acos(-1.0_dp)",
        "interface randn",
        "  module procedure randn_scalar, randn_vec, randn_mat",
        "end interface",
        "interface normrnd",
        "  module procedure normrnd_scalar, normrnd_vec, normrnd_mat",
        "end interface",
        "interface unifrnd",
        "  module procedure unifrnd_scalar, unifrnd_vec, unifrnd_mat",
        "end interface",
        "interface exprnd",
        "  module procedure exprnd_scalar, exprnd_vec, exprnd_mat",
        "end interface",
        "interface lognrnd",
        "  module procedure lognrnd_scalar, lognrnd_vec, lognrnd_mat",
        "end interface",
        "interface gamrnd",
        "  module procedure gamrnd_scalar, gamrnd_vec, gamrnd_mat",
        "end interface",
        "interface poissrnd",
        "  module procedure poissrnd_scalar, poissrnd_vec, poissrnd_mat",
        "end interface",
        "interface binornd",
        "  module procedure binornd_scalar, binornd_vec, binornd_mat",
        "end interface",
        "interface trnd",
        "  module procedure trnd_scalar, trnd_vec, trnd_mat",
        "end interface",
        "interface laprnd",
        "  module procedure laprnd_scalar, laprnd_vec, laprnd_mat",
        "end interface",
        "interface sechrnd",
        "  module procedure sechrnd_scalar, sechrnd_vec, sechrnd_mat",
        "end interface",
        "interface logisticrnd",
        "  module procedure logisticrnd_scalar, logisticrnd_vec, logisticrnd_mat",
        "end interface",
        "contains",
        "real(dp) function unit_open() result(u)",
        "call random_number(u)",
        "u = min(max(u, tiny(1.0_dp)), 1.0_dp - epsilon(1.0_dp))",
        "end function unit_open",
        "",
        "real(dp) function randn_scalar() result(x)",
        "real(dp) :: u1, u2",
        "u1 = unit_open()",
        "u2 = unit_open()",
        "x = sqrt(-2.0_dp * log(u1)) * cos(2.0_dp * pi * u2)",
        "end function randn_scalar",
        "",
        "function randn_vec(n) result(x)",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = randn_scalar()",
        "end do",
        "end function randn_vec",
        "",
        "function randn_mat(nrow, ncol) result(x)",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = randn_scalar()",
        "  end do",
        "end do",
        "end function randn_mat",
        "",
        "real(dp) function normrnd_scalar(mu, sigma) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "x = mu + sigma * randn_scalar()",
        "end function normrnd_scalar",
        "",
        "function normrnd_vec(mu, sigma, n) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "x = mu + sigma * randn_vec(n)",
        "end function normrnd_vec",
        "",
        "function normrnd_mat(mu, sigma, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "x = mu + sigma * randn_mat(nrow, ncol)",
        "end function normrnd_mat",
        "",
        "real(dp) function unifrnd_scalar(a, b) result(x)",
        "real(dp), intent(in) :: a, b",
        "x = a + (b - a) * unit_open()",
        "end function unifrnd_scalar",
        "",
        "function unifrnd_vec(a, b, n) result(x)",
        "real(dp), intent(in) :: a, b",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = unifrnd_scalar(a, b)",
        "end do",
        "end function unifrnd_vec",
        "",
        "function unifrnd_mat(a, b, nrow, ncol) result(x)",
        "real(dp), intent(in) :: a, b",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = unifrnd_scalar(a, b)",
        "  end do",
        "end do",
        "end function unifrnd_mat",
        "",
        "real(dp) function exprnd_scalar(mu) result(x)",
        "real(dp), intent(in) :: mu",
        "x = -mu * log(unit_open())",
        "end function exprnd_scalar",
        "",
        "function exprnd_vec(mu, n) result(x)",
        "real(dp), intent(in) :: mu",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = exprnd_scalar(mu)",
        "end do",
        "end function exprnd_vec",
        "",
        "function exprnd_mat(mu, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = exprnd_scalar(mu)",
        "  end do",
        "end do",
        "end function exprnd_mat",
        "",
        "real(dp) function lognrnd_scalar(mu, sigma) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "x = exp(normrnd_scalar(mu, sigma))",
        "end function lognrnd_scalar",
        "",
        "function lognrnd_vec(mu, sigma, n) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "x = exp(normrnd_vec(mu, sigma, n))",
        "end function lognrnd_vec",
        "",
        "function lognrnd_mat(mu, sigma, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu, sigma",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "x = exp(normrnd_mat(mu, sigma, nrow, ncol))",
        "end function lognrnd_mat",
        "",
        "recursive real(dp) function gamrnd_scalar(shape, scale) result(x)",
        "real(dp), intent(in) :: shape, scale",
        "real(dp) :: d, c, z, u, v",
        "if (shape <= 0.0_dp .or. scale <= 0.0_dp) then",
        "  x = 0.0_dp",
        "  return",
        "end if",
        "if (shape < 1.0_dp) then",
        "  x = gamrnd_scalar(shape + 1.0_dp, scale) * unit_open()**(1.0_dp / shape)",
        "  return",
        "end if",
        "d = shape - 1.0_dp / 3.0_dp",
        "c = 1.0_dp / sqrt(9.0_dp * d)",
        "do",
        "  z = randn_scalar()",
        "  v = (1.0_dp + c * z)**3",
        "  if (v <= 0.0_dp) cycle",
        "  u = unit_open()",
        "  if (u < 1.0_dp - 0.0331_dp * z**4) exit",
        "  if (log(u) < 0.5_dp * z**2 + d * (1.0_dp - v + log(v))) exit",
        "end do",
        "x = scale * d * v",
        "end function gamrnd_scalar",
        "",
        "function gamrnd_vec(shape, scale, n) result(x)",
        "real(dp), intent(in) :: shape, scale",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = gamrnd_scalar(shape, scale)",
        "end do",
        "end function gamrnd_vec",
        "",
        "function gamrnd_mat(shape, scale, nrow, ncol) result(x)",
        "real(dp), intent(in) :: shape, scale",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = gamrnd_scalar(shape, scale)",
        "  end do",
        "end do",
        "end function gamrnd_mat",
        "",
        "real(dp) function poissrnd_scalar(lambda) result(x)",
        "real(dp), intent(in) :: lambda",
        "real(dp) :: p, l",
        "integer :: k",
        "if (lambda <= 0.0_dp) then",
        "  x = 0.0_dp",
        "  return",
        "end if",
        "if (lambda > 100.0_dp) then",
        "  x = max(0.0_dp, anint(lambda + sqrt(lambda) * randn_scalar()))",
        "  return",
        "end if",
        "l = exp(-lambda)",
        "p = 1.0_dp",
        "k = 0",
        "do",
        "  k = k + 1",
        "  p = p * unit_open()",
        "  if (p <= l) exit",
        "end do",
        "x = real(k - 1, dp)",
        "end function poissrnd_scalar",
        "",
        "function poissrnd_vec(lambda, n) result(x)",
        "real(dp), intent(in) :: lambda",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = poissrnd_scalar(lambda)",
        "end do",
        "end function poissrnd_vec",
        "",
        "function poissrnd_mat(lambda, nrow, ncol) result(x)",
        "real(dp), intent(in) :: lambda",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = poissrnd_scalar(lambda)",
        "  end do",
        "end do",
        "end function poissrnd_mat",
        "",
        "real(dp) function binornd_scalar(ntrial, prob) result(x)",
        "real(dp), intent(in) :: ntrial, prob",
        "integer :: i, n",
        "n = max(0, int(ntrial))",
        "x = 0.0_dp",
        "do i = 1, n",
        "  if (unit_open() <= prob) x = x + 1.0_dp",
        "end do",
        "end function binornd_scalar",
        "",
        "function binornd_vec(ntrial, prob, n) result(x)",
        "real(dp), intent(in) :: ntrial, prob",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = binornd_scalar(ntrial, prob)",
        "end do",
        "end function binornd_vec",
        "",
        "function binornd_mat(ntrial, prob, nrow, ncol) result(x)",
        "real(dp), intent(in) :: ntrial, prob",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = binornd_scalar(ntrial, prob)",
        "  end do",
        "end do",
        "end function binornd_mat",
        "",
        "real(dp) function trnd_scalar(nu) result(x)",
        "real(dp), intent(in) :: nu",
        "x = randn_scalar() / sqrt(gamrnd_scalar(0.5_dp * nu, 2.0_dp) / nu)",
        "end function trnd_scalar",
        "",
        "function trnd_vec(nu, n) result(x)",
        "real(dp), intent(in) :: nu",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = trnd_scalar(nu)",
        "end do",
        "end function trnd_vec",
        "",
        "function trnd_mat(nu, nrow, ncol) result(x)",
        "real(dp), intent(in) :: nu",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = trnd_scalar(nu)",
        "  end do",
        "end do",
        "end function trnd_mat",
        "",
        "real(dp) function laprnd_scalar(mu, b) result(x)",
        "real(dp), intent(in) :: mu, b",
        "real(dp) :: u",
        "u = unit_open() - 0.5_dp",
        "x = mu - b * sign(1.0_dp, u) * log(1.0_dp - 2.0_dp * abs(u))",
        "end function laprnd_scalar",
        "",
        "function laprnd_vec(mu, b, n) result(x)",
        "real(dp), intent(in) :: mu, b",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = laprnd_scalar(mu, b)",
        "end do",
        "end function laprnd_vec",
        "",
        "function laprnd_mat(mu, b, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu, b",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = laprnd_scalar(mu, b)",
        "  end do",
        "end do",
        "end function laprnd_mat",
        "",
        "real(dp) function sechrnd_scalar(mu, s) result(x)",
        "real(dp), intent(in) :: mu, s",
        "x = mu + (2.0_dp * s / pi) * log(tan(0.5_dp * pi * unit_open()))",
        "end function sechrnd_scalar",
        "",
        "function sechrnd_vec(mu, s, n) result(x)",
        "real(dp), intent(in) :: mu, s",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = sechrnd_scalar(mu, s)",
        "end do",
        "end function sechrnd_vec",
        "",
        "function sechrnd_mat(mu, s, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu, s",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = sechrnd_scalar(mu, s)",
        "  end do",
        "end do",
        "end function sechrnd_mat",
        "",
        "real(dp) function logisticrnd_scalar(mu, s) result(x)",
        "real(dp), intent(in) :: mu, s",
        "real(dp) :: u",
        "u = unit_open()",
        "x = mu + s * log(u / (1.0_dp - u))",
        "end function logisticrnd_scalar",
        "",
        "function logisticrnd_vec(mu, s, n) result(x)",
        "real(dp), intent(in) :: mu, s",
        "integer, intent(in) :: n",
        "real(dp), allocatable :: x(:)",
        "integer :: i",
        "allocate(x(n))",
        "do i = 1, n",
        "  x(i) = logisticrnd_scalar(mu, s)",
        "end do",
        "end function logisticrnd_vec",
        "",
        "function logisticrnd_mat(mu, s, nrow, ncol) result(x)",
        "real(dp), intent(in) :: mu, s",
        "integer, intent(in) :: nrow, ncol",
        "real(dp), allocatable :: x(:,:)",
        "integer :: i, j",
        "allocate(x(nrow, ncol))",
        "do j = 1, ncol",
        "  do i = 1, nrow",
        "    x(i, j) = logisticrnd_scalar(mu, s)",
        "  end do",
        "end do",
        "end function logisticrnd_mat",
        "end module random_mod",
    ]
    return select_generic_random_module_source(lines, set(public_names), specific_names)


def select_generic_random_module_source(
    lines: list[str],
    public_names: set[str],
    specific_names: set[str] | None,
) -> list[str]:
    contains_index = lines.index("contains")
    end_index = len(lines) - 1
    first_interface = next(i for i, line in enumerate(lines) if line.startswith("interface "))
    header_lines = lines[:first_interface]
    interface_lines = lines[first_interface:contains_index]
    body_lines = lines[contains_index + 1:end_index]

    selected_interfaces: list[str] = []
    initial_needed: set[str] = set()
    i = 0
    while i < len(interface_lines):
        line = interface_lines[i]
        m = re.match(r"interface\s+([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if m is None:
            i += 1
            continue
        name = m.group(1)
        block = [line]
        i += 1
        while i < len(interface_lines):
            block.append(interface_lines[i])
            if interface_lines[i].startswith("end interface"):
                i += 1
                break
            i += 1
        if name in public_names:
            selected_block: list[str] = []
            for block_line in block:
                proc = re.match(r"\s*module procedure\s+(.+)", block_line)
                if proc is not None:
                    parts = [part.strip() for part in proc.group(1).split(",")]
                    if specific_names is not None:
                        parts = [part for part in parts if part in specific_names]
                    initial_needed.update(parts)
                    if parts:
                        selected_block.append("  module procedure " + ", ".join(parts))
                else:
                    selected_block.append(block_line)
            if any(line.strip().startswith("module procedure") for line in selected_block):
                selected_interfaces.extend(selected_block)

    blocks = split_helper_blocks(body_lines)
    helper_names = {name for name, _ in blocks}
    needed = initial_needed & helper_names
    changed = True
    while changed:
        changed = False
        for name, block in blocks:
            if name not in needed:
                continue
            refs = helper_references("\n".join(block[1:]), helper_names) - needed
            if refs:
                needed.update(refs)
                changed = True

    selected: list[str] = []
    selected.extend(header_lines)
    selected.extend(selected_interfaces)
    selected.append("contains")
    first = True
    for name, block in blocks:
        if name not in needed:
            continue
        if not first:
            selected.append("")
        selected.extend(block)
        first = False
    selected.append("end module random_mod")
    return selected


def split_helper_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    for line in lines:
        if line == "":
            if current:
                name = helper_block_name(current)
                if name is not None:
                    blocks.append((name, current))
                current = []
        else:
            current.append(line)
    if current:
        name = helper_block_name(current)
        if name is not None:
            blocks.append((name, current))
    return blocks


def helper_block_name(block: list[str]) -> str | None:
    m = re.match(r"^(?:[A-Za-z0-9_(), ]+\s+)?(?:function|subroutine)\s+([A-Za-z_][A-Za-z0-9_]*)\b", block[0])
    return None if m is None else m.group(1)


def helper_references(text: str, helper_names: set[str]) -> set[str]:
    refs: set[str] = set()
    for name in helper_names:
        if re.search(rf"\b{re.escape(name)}\s*\(", text):
            refs.add(name)
    return refs


def mark_helper_pure(block: list[str]) -> list[str]:
    name = helper_block_name(block)
    if name not in PURE_HELPERS:
        return block
    out = block.copy()
    if not out[0].lower().startswith("pure "):
        out[0] = "pure " + out[0]
    return out


def select_helper_source(lines: list[str], body_lines: list[str] | None) -> list[str]:
    if body_lines is None:
        return lines
    blocks = split_helper_blocks(lines)
    helper_names = {name for name, _ in blocks}
    needed: set[str] = set()
    for line in body_lines:
        needed.update(helper_references(line, helper_names))
    changed = True
    while changed:
        changed = False
        for name, block in blocks:
            if name not in needed:
                continue
            refs = helper_references("\n".join(block[1:]), helper_names) - needed
            if refs:
                needed.update(refs)
                changed = True

    selected: list[str] = []
    for name, block in blocks:
        if name in needed:
            if selected:
                selected.append("")
            selected.extend(mark_helper_pure(block))
    return selected


def helper_source(include_linspace: bool, body_lines: list[str] | None = None) -> list[str]:
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
        "function reshape_vec_from_vec_omat(x, n) result(y)",
        "real(real64), intent(in) :: x(:)",
        "integer, intent(in) :: n",
        "real(real64), allocatable :: y(:)",
        "if (n /= size(x)) then",
        "  print *, 'omat reshape size mismatch'",
        "  stop 1",
        "end if",
        "allocate(y(n))",
        "y = reshape(x, [n])",
        "end function reshape_vec_from_vec_omat",
        "",
        "function reshape_vec_from_mat_omat(x, n) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "integer, intent(in) :: n",
        "real(real64), allocatable :: y(:)",
        "if (n /= size(x)) then",
        "  print *, 'omat reshape size mismatch'",
        "  stop 1",
        "end if",
        "allocate(y(n))",
        "y = reshape(x, [n])",
        "end function reshape_vec_from_mat_omat",
        "",
        "function reshape_mat_from_vec_omat(x, nrow, ncol) result(y)",
        "real(real64), intent(in) :: x(:)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: y(:,:)",
        "if (nrow * ncol /= size(x)) then",
        "  print *, 'omat reshape size mismatch'",
        "  stop 1",
        "end if",
        "allocate(y(nrow, ncol))",
        "y = reshape(x, [nrow, ncol])",
        "end function reshape_mat_from_vec_omat",
        "",
        "function reshape_mat_from_mat_omat(x, nrow, ncol) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: y(:,:)",
        "if (nrow * ncol /= size(x)) then",
        "  print *, 'omat reshape size mismatch'",
        "  stop 1",
        "end if",
        "allocate(y(nrow, ncol))",
        "y = reshape(x, [nrow, ncol])",
        "end function reshape_mat_from_mat_omat",
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
        "",
        "real(real64) function mean_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "mean_vec_omat = sum(x) / real(size(x), real64)",
        "end function mean_vec_omat",
        "",
        "function mean_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = mean_vec_omat(x(:, j))",
        "end do",
        "end function mean_mat_omat",
        "",
        "real(real64) function var_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "real(real64) :: xmean",
        "if (size(x) <= 1) then",
        "  var_vec_omat = 0.0_real64",
        "else",
        "  xmean = mean_vec_omat(x)",
        "  var_vec_omat = sum((x - xmean)**2) / real(size(x) - 1, real64)",
        "end if",
        "end function var_vec_omat",
        "",
        "function var_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = var_vec_omat(x(:, j))",
        "end do",
        "end function var_mat_omat",
        "",
        "real(real64) function std_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "std_vec_omat = sqrt(var_vec_omat(x))",
        "end function std_vec_omat",
        "",
        "function std_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = std_vec_omat(x(:, j))",
        "end do",
        "end function std_mat_omat",
        "",
        "real(real64) function rms_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "if (size(x) <= 0) then",
        "  rms_vec_omat = 0.0_real64",
        "else",
        "  rms_vec_omat = sqrt(sum(x**2) / real(size(x), real64))",
        "end if",
        "end function rms_vec_omat",
        "",
        "function rms_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = rms_vec_omat(x(:, j))",
        "end do",
        "end function rms_mat_omat",
        "",
        "real(real64) function median_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "real(real64) :: tmp",
        "integer :: i, j, n",
        "n = size(x)",
        "allocate(y(n))",
        "y = x",
        "do i = 2, n",
        "  tmp = y(i)",
        "  j = i - 1",
        "  do while (j >= 1)",
        "    if (y(j) <= tmp) exit",
        "    y(j + 1) = y(j)",
        "    j = j - 1",
        "  end do",
        "  y(j + 1) = tmp",
        "end do",
        "if (mod(n, 2) == 1) then",
        "  median_vec_omat = y((n + 1) / 2)",
        "else",
        "  median_vec_omat = 0.5_real64 * (y(n / 2) + y(n / 2 + 1))",
        "end if",
        "end function median_vec_omat",
        "",
        "function median_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = median_vec_omat(x(:, j))",
        "end do",
        "end function median_mat_omat",
        "",
        "real(real64) function mad_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "mad_vec_omat = median_vec_omat(abs(x - median_vec_omat(x)))",
        "end function mad_vec_omat",
        "",
        "function mad_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = mad_vec_omat(x(:, j))",
        "end do",
        "end function mad_mat_omat",
        "",
        "real(real64) function quantile_vec_omat(x, p)",
        "real(real64), intent(in) :: x(:), p",
        "real(real64), allocatable :: y(:)",
        "real(real64) :: pos, frac, tmp, pp",
        "integer :: i, j, lo, hi, n",
        "n = size(x)",
        "if (n <= 0) then",
        "  quantile_vec_omat = 0.0_real64",
        "  return",
        "end if",
        "allocate(y(n))",
        "y = x",
        "do i = 2, n",
        "  tmp = y(i)",
        "  j = i - 1",
        "  do while (j >= 1)",
        "    if (y(j) <= tmp) exit",
        "    y(j + 1) = y(j)",
        "    j = j - 1",
        "  end do",
        "  y(j + 1) = tmp",
        "end do",
        "pp = max(0.0_real64, min(1.0_real64, p))",
        "pos = 1.0_real64 + pp * real(n - 1, real64)",
        "lo = int(floor(pos))",
        "hi = int(ceiling(pos))",
        "frac = pos - real(lo, real64)",
        "quantile_vec_omat = (1.0_real64 - frac) * y(lo) + frac * y(hi)",
        "end function quantile_vec_omat",
        "",
        "function quantile_mat_omat(x, p) result(y)",
        "real(real64), intent(in) :: x(:,:), p",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = quantile_vec_omat(x(:, j), p)",
        "end do",
        "end function quantile_mat_omat",
        "",
        "real(real64) function prctile_vec_omat(x, p)",
        "real(real64), intent(in) :: x(:), p",
        "prctile_vec_omat = quantile_vec_omat(x, p / 100.0_real64)",
        "end function prctile_vec_omat",
        "",
        "function prctile_mat_omat(x, p) result(y)",
        "real(real64), intent(in) :: x(:,:), p",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = prctile_vec_omat(x(:, j), p)",
        "end do",
        "end function prctile_mat_omat",
        "",
        "real(real64) function iqr_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "iqr_vec_omat = quantile_vec_omat(x, 0.75_real64) - quantile_vec_omat(x, 0.25_real64)",
        "end function iqr_vec_omat",
        "",
        "function iqr_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = iqr_vec_omat(x(:, j))",
        "end do",
        "end function iqr_mat_omat",
        "",
        "real(real64) function skewness_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "real(real64) :: xmean, m2, m3, g1",
        "integer :: n",
        "n = size(x)",
        "if (n <= 2) then",
        "  skewness_vec_omat = 0.0_real64",
        "  return",
        "end if",
        "xmean = mean_vec_omat(x)",
        "m2 = sum((x - xmean)**2) / real(n, real64)",
        "if (m2 == 0.0_real64) then",
        "  skewness_vec_omat = 0.0_real64",
        "else",
        "  m3 = sum((x - xmean)**3) / real(n, real64)",
        "  g1 = m3 / (m2**1.5_real64)",
        "  skewness_vec_omat = sqrt(real(n * (n - 1), real64)) * g1 / real(n - 2, real64)",
        "end if",
        "end function skewness_vec_omat",
        "",
        "function skewness_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = skewness_vec_omat(x(:, j))",
        "end do",
        "end function skewness_mat_omat",
        "",
        "real(real64) function kurtosis_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "real(real64) :: xmean, m2, m4, b2",
        "integer :: n",
        "n = size(x)",
        "if (n <= 1) then",
        "  kurtosis_vec_omat = 0.0_real64",
        "  return",
        "end if",
        "xmean = mean_vec_omat(x)",
        "m2 = sum((x - xmean)**2) / real(n, real64)",
        "if (m2 == 0.0_real64) then",
        "  kurtosis_vec_omat = 0.0_real64",
        "else",
        "  m4 = sum((x - xmean)**4) / real(n, real64)",
        "  b2 = m4 / (m2 * m2)",
        "  if (n > 3) then",
        "    kurtosis_vec_omat = real(n - 1, real64) * (real(n + 1, real64) * b2 - &",
        "         3.0_real64 * real(n - 1, real64)) / &",
        "         (real(n - 2, real64) * real(n - 3, real64)) + 3.0_real64",
        "  else",
        "    kurtosis_vec_omat = b2",
        "  end if",
        "end if",
        "end function kurtosis_vec_omat",
        "",
        "function kurtosis_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = kurtosis_vec_omat(x(:, j))",
        "end do",
        "end function kurtosis_mat_omat",
        "",
        "function cumsum_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i",
        "allocate(y(size(x)))",
        "if (size(x) >= 1) y(1) = x(1)",
        "do i = 2, size(x)",
        "  y(i) = y(i - 1) + x(i)",
        "end do",
        "end function cumsum_vec_omat",
        "",
        "function cumsum_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i, j",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  if (size(x, 1) >= 1) y(1, j) = x(1, j)",
        "  do i = 2, size(x, 1)",
        "    y(i, j) = y(i - 1, j) + x(i, j)",
        "  end do",
        "end do",
        "end function cumsum_mat_omat",
        "",
        "function zscore_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "real(real64) :: xmean, xsd",
        "allocate(y(size(x)))",
        "xmean = mean_vec_omat(x)",
        "xsd = std_vec_omat(x)",
        "if (xsd == 0.0_real64) then",
        "  y = 0.0_real64",
        "else",
        "  y = (x - xmean) / xsd",
        "end if",
        "end function zscore_vec_omat",
        "",
        "function zscore_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: j",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(:, j) = zscore_vec_omat(x(:, j))",
        "end do",
        "end function zscore_mat_omat",
        "",
        "function movmean_vec_omat(x, k) result(y)",
        "real(real64), intent(in) :: x(:)",
        "integer, intent(in) :: k",
        "real(real64), allocatable :: y(:)",
        "integer :: i, lo, hi, left, right, kk",
        "kk = max(1, k)",
        "left = (kk - 1) / 2",
        "right = kk / 2",
        "allocate(y(size(x)))",
        "do i = 1, size(x)",
        "  lo = max(1, i - left)",
        "  hi = min(size(x), i + right)",
        "  y(i) = sum(x(lo:hi)) / real(hi - lo + 1, real64)",
        "end do",
        "end function movmean_vec_omat",
        "",
        "function movmean_mat_omat(x, k) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "integer, intent(in) :: k",
        "real(real64), allocatable :: y(:,:)",
        "integer :: j",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(:, j) = movmean_vec_omat(x(:, j), k)",
        "end do",
        "end function movmean_mat_omat",
        "",
        "function diff_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "integer :: n",
        "n = size(x)",
        "allocate(y(max(0, n - 1)))",
        "if (n > 1) y = x(2:n) - x(1:n-1)",
        "end function diff_vec_omat",
        "",
        "function sort_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "real(real64) :: tmp",
        "integer :: i, j",
        "allocate(y(size(x)))",
        "y = x",
        "do i = 1, size(y) - 1",
        "  do j = i + 1, size(y)",
        "    if (y(j) < y(i)) then",
        "      tmp = y(i)",
        "      y(i) = y(j)",
        "      y(j) = tmp",
        "    end if",
        "  end do",
        "end do",
        "end function sort_vec_omat",
        "",
        "function find_vec_omat(mask) result(idx)",
        "logical, intent(in) :: mask(:)",
        "integer, allocatable :: idx(:)",
        "integer :: i, n",
        "n = count(mask)",
        "allocate(idx(n))",
        "n = 0",
        "do i = 1, size(mask)",
        "  if (mask(i)) then",
        "    n = n + 1",
        "    idx(n) = i",
        "  end if",
        "end do",
        "end function find_vec_omat",
        "",
        "function isnan_vec_omat(x) result(mask)",
        "real(real64), intent(in) :: x(:)",
        "logical, allocatable :: mask(:)",
        "allocate(mask(size(x)))",
        "mask = x /= x",
        "end function isnan_vec_omat",
        "",
        "function isfinite_vec_omat(x) result(mask)",
        "real(real64), intent(in) :: x(:)",
        "logical, allocatable :: mask(:)",
        "allocate(mask(size(x)))",
        "mask = x == x .and. abs(x) <= huge(x)",
        "end function isfinite_vec_omat",
        "",
        "function isinf_vec_omat(x) result(mask)",
        "real(real64), intent(in) :: x(:)",
        "logical, allocatable :: mask(:)",
        "allocate(mask(size(x)))",
        "mask = x == x .and. abs(x) > huge(x)",
        "end function isinf_vec_omat",
        "",
        "logical function any_vec_omat(mask)",
        "logical, intent(in) :: mask(:)",
        "any_vec_omat = any(mask)",
        "end function any_vec_omat",
        "",
        "logical function all_vec_omat(mask)",
        "logical, intent(in) :: mask(:)",
        "all_vec_omat = all(mask)",
        "end function all_vec_omat",
        "",
        "function cov_omat(x) result(c)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: c(:,:)",
        "real(real64), allocatable :: xmean(:)",
        "integer :: i, j, k, nobs, nvar",
        "nobs = size(x, 1)",
        "nvar = size(x, 2)",
        "allocate(c(nvar, nvar), xmean(nvar))",
        "xmean = mean_mat_omat(x)",
        "c = 0.0_real64",
        "if (nobs <= 1) return",
        "do j = 1, nvar",
        "  do k = j, nvar",
        "    do i = 1, nobs",
        "      c(j, k) = c(j, k) + (x(i, j) - xmean(j)) * (x(i, k) - xmean(k))",
        "    end do",
        "    c(j, k) = c(j, k) / real(nobs - 1, real64)",
        "    c(k, j) = c(j, k)",
        "  end do",
        "end do",
        "end function cov_omat",
        "",
        "real(real64) function corr_omat(x, y)",
        "real(real64), intent(in) :: x(:), y(:)",
        "real(real64) :: xsd, ysd",
        "if (size(x) /= size(y)) then",
        "  print *, 'omat corr size mismatch'",
        "  stop 1",
        "end if",
        "xsd = std_vec_omat(x)",
        "ysd = std_vec_omat(y)",
        "if (xsd == 0.0_real64 .or. ysd == 0.0_real64) then",
        "  corr_omat = 0.0_real64",
        "else",
        "  corr_omat = sum((x - mean_vec_omat(x)) * (y - mean_vec_omat(y))) / &",
        "       (real(size(x) - 1, real64) * xsd * ysd)",
        "end if",
        "end function corr_omat",
        "",
        "function corrcoef_omat(x) result(r)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: r(:,:)",
        "real(real64), allocatable :: s(:)",
        "integer :: j, k, nvar",
        "nvar = size(x, 2)",
        "allocate(r(nvar, nvar), s(nvar))",
        "r = cov_omat(x)",
        "s = std_mat_omat(x)",
        "do j = 1, nvar",
        "  do k = 1, nvar",
        "    if (s(j) == 0.0_real64 .or. s(k) == 0.0_real64) then",
        "      r(j, k) = 0.0_real64",
        "    else",
        "      r(j, k) = r(j, k) / (s(j) * s(k))",
        "    end if",
        "  end do",
        "end do",
        "end function corrcoef_omat",
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
    return select_helper_source(lines, body_lines)


def translate_source(source: str, generic: bool = False) -> str:
    return Translator(generic=generic).translate(source)


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
        return ExecResult(2, "", "omat: gfortran not found; use --translate or -o to inspect generated Fortran\n")

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


def summarize_repl_random_assignment(
    rhs: str,
    scalar_values: dict[str, float],
    materialize_limit: int,
) -> str | None:
    call = parse_simple_call(rhs)
    if call is None:
        return None
    name, args = call
    if name == "rand":
        size_args = args
    elif name in RANDOM_DIST_PARAM_COUNTS:
        nparam = RANDOM_DIST_PARAM_COUNTS[name]
        if len(args) <= nparam:
            return None
        size_args = args[nparam:]
    else:
        return None
    try:
        if len(size_args) == 1:
            n = parse_repl_size_arg(size_args[0], scalar_values)
            return None if n <= materialize_limit else f"{name}({n})  ({n} values)\n"
        if len(size_args) == 2:
            nrow = parse_repl_size_arg(size_args[0], scalar_values)
            ncol = parse_repl_size_arg(size_args[1], scalar_values)
            if ncol == 1:
                return None if nrow <= materialize_limit else f"{name}({nrow})  ({nrow} values)\n"
            if nrow * ncol <= materialize_limit:
                return None
            return f"{name}({nrow}, {ncol})\n({nrow}x{ncol} matrix)\n"
    except OmatError:
        return None
    return None


def summarize_repl_assignment(
    line: str,
    scalar_values: dict[str, float] | None = None,
    materialize_limit: int = DEFAULT_MATERIALIZE_RAND_LIMIT,
) -> str | None:
    stripped = strip_comment(line).strip()
    if stripped.endswith(";"):
        return None
    m = ASSIGN_RE.match(stripped)
    if not m:
        return None
    _, rhs = m.groups()
    rhs = rhs.strip()
    rand_summary = summarize_repl_random_assignment(rhs, scalar_values or {}, materialize_limit)
    if rand_summary is not None:
        return rand_summary
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


def run_repl_candidate(
    buffer: list[str],
    line: str,
    ofort: str,
    scalar_values: dict[str, float],
    materialize_limit: int,
) -> str | None:
    source_lines = [suppress_repl_output(prior) for prior in buffer]
    summary = summarize_repl_assignment(line, scalar_values, materialize_limit)
    source_lines.append(suppress_repl_output(line) if summary is not None else line)
    return run_repl_source(source_lines, ofort, summary)


def report_omat_error(exc: OmatError) -> None:
    print(f"omat: {exc}", file=sys.stderr)


def save_repl_file(path: str | None, text: str, label: str) -> None:
    if path is None or not text:
        return
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"omat: could not save {label}: {exc}", file=sys.stderr)
        return
    print(f"wrote {path}", file=sys.stderr)


def incomplete_generic_source(source: str, reason: str, fortran_path: str | None) -> str:
    lines = [
        "! WARNING: generic_session.f90 is incomplete.",
        f"! Reason: {reason}",
    ]
    if fortran_path is not None:
        lines.append(f"! The complete ofort-oriented Fortran was written to {fortran_path}.")
    lines.extend(["!", "! Accepted omat source:"])
    lines.extend("!   " + line for line in source.splitlines())
    lines.append("")
    return "\n".join(lines)


def save_repl_session(
    buffer: list[str],
    fortran_path: str | None,
    source_path: str | None,
    generic_fortran_path: str | None,
) -> None:
    if not buffer:
        return
    if fortran_path is None and source_path is None and generic_fortran_path is None:
        return
    source = "\n".join(buffer) + "\n"
    save_repl_file(source_path, source, "source")
    generated: str | None = None
    if fortran_path is not None or generic_fortran_path is not None:
        try:
            generated = translate_source(source)
        except OmatError as exc:
            print(f"omat: could not save Fortran: {exc}", file=sys.stderr)
    if generated is not None and fortran_path is not None:
        save_repl_file(fortran_path, generated, "Fortran")
    if generic_fortran_path is not None:
        try:
            generic_generated = translate_source(source, generic=True)
        except OmatError as exc:
            print(f"omat: generic Fortran incomplete: {exc}", file=sys.stderr)
            generic_generated = incomplete_generic_source(source, str(exc), fortran_path if generated is not None else None)
        save_repl_file(generic_fortran_path, generic_generated, "generic Fortran")


def repl(
    ofort: str,
    materialize_rand_limit: int = DEFAULT_MATERIALIZE_RAND_LIMIT,
    session_fortran: str | None = DEFAULT_SESSION_FORTRAN,
    session_source: str | None = DEFAULT_SESSION_SOURCE,
    generic_session_fortran: str | None = DEFAULT_GENERIC_SESSION_FORTRAN,
) -> int:
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
            save_repl_session(buffer, session_fortran, session_source, generic_session_fortran)
            return 0
        command = line.strip().lower()
        if command in {"quit", "q", "exit"}:
            save_repl_session(buffer, session_fortran, session_source, generic_session_fortran)
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
        if command in {"fortran", "fortran ofort", "fortran generic"}:
            try:
                print(translate_source("\n".join(buffer), generic=(command == "fortran generic")), end="")
            except OmatError as exc:
                print(f"omat: {exc}", file=sys.stderr)
            continue
        if command in {"run", "."}:
            run_repl_buffer(buffer, ofort)
            continue
        try:
            materialized_line = materialize_repl_rand(line, scalar_values, materialize_rand_limit)
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
        stdout = run_repl_candidate(buffer, materialized_line, ofort, scalar_values, materialize_rand_limit)
        if stdout is not None:
            buffer = candidate
            update_scalar_values(materialized_line, scalar_values)
            block_depth = new_block_depth


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Translate a small MATLAB/Octave-like numerical subset to Fortran and optionally run it."
    )
    parser.add_argument("source", nargs="?", help="MATLAB/Octave-like source file")
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="write the active Fortran translation to FILE; implies --translate unless --run is also given",
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="translate only; print the active Fortran translation to stdout unless an output file is given",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="run after translating, even when output files are requested",
    )
    parser.add_argument(
        "--generic",
        action="store_true",
        help="generate generic Fortran instead of ofort-oriented Fortran for the active translation",
    )
    parser.add_argument(
        "--ofort-out",
        metavar="FILE",
        help="write ofort-oriented Fortran to FILE; implies --translate unless --run is also given",
    )
    parser.add_argument(
        "--generic-out",
        metavar="FILE",
        help="write generic Fortran to FILE; implies --translate unless --run is also given",
    )
    parser.add_argument("--emit-fortran", metavar="FILE", help="alias for -o FILE")
    parser.add_argument("--no-run", action="store_true", help="translate only; do not compile or run")
    parser.add_argument("--gfortran", default="gfortran", help="gfortran command (default: gfortran)")
    parser.add_argument(
        "--ofort",
        default=str(DEFAULT_OFORT),
        help=f"ofort command for REPL execution (default: {DEFAULT_OFORT})",
    )
    parser.add_argument("--keep", action="store_true", help="keep generated temporary files")
    parser.add_argument(
        "--session-fortran",
        default=DEFAULT_SESSION_FORTRAN,
        metavar="FILE",
        help=f"in REPL mode, save accepted lines as Fortran on exit (default: {DEFAULT_SESSION_FORTRAN})",
    )
    parser.add_argument(
        "--session-source",
        default=DEFAULT_SESSION_SOURCE,
        metavar="FILE",
        help=f"in REPL mode, save accepted input lines on exit (default: {DEFAULT_SESSION_SOURCE})",
    )
    parser.add_argument(
        "--generic-session-fortran",
        default=DEFAULT_GENERIC_SESSION_FORTRAN,
        metavar="FILE",
        help=(
            "in REPL mode, save generic Fortran on exit, or an incomplete warning file "
            f"if generic generation is not available (default: {DEFAULT_GENERIC_SESSION_FORTRAN})"
        ),
    )
    parser.add_argument(
        "--no-save-session",
        action="store_true",
        help="in REPL mode, do not save generated Fortran on exit",
    )
    parser.add_argument(
        "--materialize-rand-limit",
        type=int,
        default=DEFAULT_MATERIALIZE_RAND_LIMIT,
        metavar="N",
        help=(
            "in the REPL, store rand(...) calls as literal values only up to N total elements "
            f"(default: {DEFAULT_MATERIALIZE_RAND_LIMIT})"
        ),
    )
    args = parser.parse_args(argv)
    if args.materialize_rand_limit < 0:
        print("omat: --materialize-rand-limit must be non-negative", file=sys.stderr)
        return 2
    if args.run and args.no_run:
        print("omat: --run and --no-run cannot both be used", file=sys.stderr)
        return 2
    if args.output and args.emit_fortran:
        print("omat: use either -o/--output or --emit-fortran, not both", file=sys.stderr)
        return 2
    output_path = args.output or args.emit_fortran

    if args.source is None:
        source_options = [
            output_path,
            args.translate,
            args.run,
            args.no_run,
            args.keep,
            args.generic,
            args.ofort_out,
            args.generic_out,
        ]
        if any(source_options):
            print(
                "omat: source file is required with translation, output, run, generic, or keep options",
                file=sys.stderr,
            )
            return 2
        session_fortran = None if args.no_save_session else args.session_fortran
        session_source = None if args.no_save_session else args.session_source
        generic_session_fortran = None if args.no_save_session else args.generic_session_fortran
        return repl(
            args.ofort,
            args.materialize_rand_limit,
            session_fortran,
            session_source,
            generic_session_fortran,
        )

    source_path = Path(args.source)
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"omat: could not read {source_path}: {exc}", file=sys.stderr)
        return 1

    generated_cache: dict[bool, str] = {}

    def generated_for(generic: bool) -> str:
        if generic not in generated_cache:
            generated_cache[generic] = translate_source(source_text, generic=generic)
        return generated_cache[generic]

    try:
        active_generated = generated_for(args.generic)
        if args.ofort_out:
            Path(args.ofort_out).write_text(generated_for(False), encoding="utf-8")
        if args.generic_out:
            Path(args.generic_out).write_text(generated_for(True), encoding="utf-8")
        if output_path:
            Path(output_path).write_text(active_generated, encoding="utf-8")
    except OmatError as exc:
        print(f"omat: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"omat: could not write output: {exc}", file=sys.stderr)
        return 1

    explicit_output = output_path is not None or args.ofort_out is not None or args.generic_out is not None
    translate_only = args.translate or args.no_run or (explicit_output and not args.run)
    if translate_only:
        if not explicit_output:
            print(active_generated, end="")
        return 0

    keep_path = source_path.with_suffix(".f90") if args.keep else None
    if args.generic:
        return compile_and_run(active_generated, args.gfortran, output_path, keep_path)
    if "use ofort_la_mod" in active_generated or "use ofort_random_mod" in active_generated:
        return run_with_ofort(active_generated, args.ofort, keep_path)
    return compile_and_run(active_generated, args.gfortran, output_path, keep_path)


if __name__ == "__main__":
    raise SystemExit(run())
