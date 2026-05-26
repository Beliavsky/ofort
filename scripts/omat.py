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
import time
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
MULTI_ASSIGN_RE = re.compile(
    r"^\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\]\s*=\s*(.+)$"
)
CONST_ASSIGN_RE = re.compile(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)
FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)
IF_RE = re.compile(r"^if\s+(.+)$", re.IGNORECASE)
ELSEIF_RE = re.compile(r"^elseif\s+(.+)$", re.IGNORECASE)


BUILTINS = {
    "abs",
    "acos",
    "all",
    "any",
    "asin",
    "atan",
    "cos",
    "ceil",
    "equicor",
    "exp",
    "exist",
    "fix",
    "flip",
    "fliplr",
    "flipud",
    "floor",
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
    "cumprod",
    "cumtrapz",
    "diag",
    "diff",
    "eye",
    "find",
    "iqr",
    "isfinite",
    "isinf",
    "isempty",
    "ismember",
    "ismatrix",
    "isnan",
    "isscalar",
    "isvector",
    "int8",
    "int16",
    "int32",
    "int64",
    "kurtosis",
    "length",
    "logspace",
    "movmean",
    "mod",
    "nonzeros",
    "normcdf",
    "numel",
    "prctile",
    "prod",
    "quantile",
    "randi",
    "repmat",
    "reshape",
    "rms",
    "round",
    "sqrt",
    "std",
    "skewness",
    "sin",
    "sign",
    "size",
    "sum",
    "sort",
    "tan",
    "trapz",
    "transpose",
    "unique",
    "intersect",
    "union",
    "setdiff",
    "var",
    "zscore",
}

INTEGER_CONSTRUCTORS = {"int8", "int16", "int32", "int64"}

MATRIX_FUNC_RE = re.compile(r"^(rand|zeros|ones)\s*\((.*)\)$", re.IGNORECASE)
STAT_SCALAR_FUNCTIONS = {
    "mean", "std", "var", "median", "skewness", "kurtosis", "rms", "mad",
    "quantile", "prctile", "iqr", "corr", "trapz"
}
STAT_VECTOR_FUNCTIONS = {"cumsum", "cumprod", "cumtrapz", "zscore", "movmean"}
STAT_MATRIX_FUNCTIONS = {"cov", "corrcoef"}
LA_SCALAR_FUNCTIONS = {"trace", "det", "cond", "norm", "rank", "is_square", "is_diagonal", "is_symmetric", "is_invertible"}
LA_VECTOR_FUNCTIONS = {"eig", "svd"}
LA_MATRIX_FUNCTIONS = {"triu", "tril", "kron", "inv", "qr", "lu", "pinv", "chol", "outer_product", "transpose2", "matmul2", "crossprod", "tcrossprod"}
LA_FUNCTIONS = LA_SCALAR_FUNCTIONS | LA_VECTOR_FUNCTIONS | LA_MATRIX_FUNCTIONS | {"solve", "mldivide", "col_sums", "col_means"}
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
    "mean_mat_dim2_omat",
    "var_vec_omat",
    "var_mat_omat",
    "std_vec_omat",
    "std_mat_omat",
    "std_mat_dim2_omat",
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
    "logspace_omat",
    "colon2_omat",
    "colon3_omat",
    "eye_omat",
    "diag_vec_omat",
    "diag_mat_omat",
    "repmat_vec_omat",
    "repmat_mat_omat",
    "min_vec_omat",
    "min_mat_omat",
    "max_vec_omat",
    "max_mat_omat",
    "prod_vec_omat",
    "prod_mat_omat",
    "cumprod_vec_omat",
    "cumprod_mat_omat",
    "ceil_vec_omat",
    "ceil_mat_omat",
    "floor_vec_omat",
    "floor_mat_omat",
    "round_vec_omat",
    "round_mat_omat",
    "fix_vec_omat",
    "fix_mat_omat",
    "sign_vec_omat",
    "sign_mat_omat",
    "flip_vec_omat",
    "flip_mat_omat",
    "fliplr_mat_omat",
    "flipud_mat_omat",
    "transpose_vec_omat",
    "transpose_mat_omat",
    "vcat_vecs_omat",
    "diff_vec_omat",
    "sort_vec_omat",
    "find_vec_omat",
    "find_k_vec_omat",
    "unique_vec_omat",
    "intersect_vec_omat",
    "union_vec_omat",
    "setdiff_vec_omat",
    "ismember_vec_omat",
    "nonzeros_vec_omat",
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
    constant: bool = False
    value: str | None = None


@dataclass
class Statement:
    text: str
    indent: int


@dataclass
class LocalFunction:
    name: str
    result: str
    args: list[str]
    body: list[tuple[int, str]]


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


class OmatError(Exception):
    pass


class Translator:
    def __init__(self, generic: bool = False, source_path: Path | None = None) -> None:
        self.symbols: dict[str, Symbol] = {}
        self.statements: list[Statement] = []
        self.indent = 0
        self.block_stack: list[str] = []
        self.needs_linstep = False
        self.needs_la_mod = False
        self.la_names: set[str] = set()
        self.needs_random_mod = False
        self.random_names: set[str] = set()
        self.random_specific_names: set[str] = set()
        self.integer_env_kinds: set[str] = set()
        self.generic = generic
        self.function_search_dir = source_path.parent if source_path is not None else None
        self.loading_functions: set[str] = set()
        self.local_functions: dict[str, LocalFunction] = {}
        self.local_function_signatures: dict[str, tuple[list[str], str]] = {}
        self.textscan_units: dict[str, str] = {}
        self.textscan_columns: dict[str, dict[int, str]] = {}

    def translate(self, source: str) -> str:
        source = join_multiline_statements(source)
        main_lines, local_functions = split_local_functions(source)
        self.local_functions = {func.name.lower(): func for func in local_functions}
        for line_no, raw in main_lines:
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
        const_directive = has_omat_const_directive(raw)
        line = strip_comment(raw).strip()
        if not line:
            return
        suppress_output = line.endswith(";")
        if suppress_output:
            line = line[:-1].rstrip()
        if not line:
            return

        const_assignment = CONST_ASSIGN_RE.match(line)
        if const_assignment is not None:
            name, rhs = const_assignment.groups()
            const_directive = True
            line = f"{name} = {rhs.strip()}"

        low = line.lower()
        if low in {"clear", "clc"}:
            return
        if low == "end":
            if self.indent <= 0:
                raise OmatError(f"line {line_no}: END without a block")
            if not self.block_stack:
                raise OmatError(f"line {line_no}: END without a block")
            block = self.block_stack.pop()
            self.indent -= 1
            self.statements.append(Statement("end do" if block == "for" else "end if", self.indent))
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
            self.block_stack.append("for")
            return

        m = IF_RE.match(line)
        if m:
            condition = m.group(1).strip()
            self.statements.append(Statement(f"if ({self.expr(condition)}) then", self.indent))
            self.indent += 1
            self.block_stack.append("if")
            return

        m = ELSEIF_RE.match(line)
        if m:
            if not self.block_stack or self.block_stack[-1] != "if":
                raise OmatError(f"line {line_no}: ELSEIF without IF")
            if self.indent <= 0:
                raise OmatError(f"line {line_no}: ELSEIF without IF")
            self.indent -= 1
            self.statements.append(Statement(f"else if ({self.expr(m.group(1).strip())}) then", self.indent))
            self.indent += 1
            return

        if low == "else":
            if not self.block_stack or self.block_stack[-1] != "if":
                raise OmatError(f"line {line_no}: ELSE without IF")
            if self.indent <= 0:
                raise OmatError(f"line {line_no}: ELSE without IF")
            self.indent -= 1
            self.statements.append(Statement("else", self.indent))
            self.indent += 1
            return

        if low.startswith("disp(") and line.endswith(")"):
            arg = line[line.find("(") + 1 : -1]
            if not suppress_output:
                self.emit_display(arg)
            return

        call = parse_simple_call(line)
        if call is not None and call[0] == "fprintf":
            self.statements.append(Statement(self.fprintf_statement(call[1], line_no), self.indent))
            return
        if call is not None and call[0] == "fclose" and len(call[1]) == 1:
            self.statements.append(Statement(f"close({self.expr(call[1][0])})", self.indent))
            return

        mask_assignment = self.parse_logical_index_assignment(line)
        if mask_assignment is not None:
            name, mask, rhs = mask_assignment
            existing = self.symbols.get(name.lower())
            if existing is not None and existing.constant:
                raise OmatError(f"line {line_no}: cannot assign to constant '{name}'")
            self.statements.append(Statement(f"where ({mask})", self.indent))
            self.indent += 1
            self.statements.append(Statement(f"{name} = {rhs}", self.indent))
            self.indent -= 1
            self.statements.append(Statement("end where", self.indent))
            if not suppress_output:
                sym = self.symbols.get(name.lower())
                if sym is not None:
                    self.statements.append(Statement(self.display_statement(name, sym.kind), self.indent))
            return

        m = ASSIGN_RE.match(line)
        if m:
            name, rhs = m.groups()
            cell = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*([12])\s*\}$", rhs.strip())
            if cell and cell.group(1).lower() in self.textscan_units:
                data_name = cell.group(1).lower()
                col = int(cell.group(2))
                kind = "string_vector" if col == 1 else "real_vector"
                existing = self.symbols.get(name.lower())
                if existing is not None and existing.kind != kind:
                    raise OmatError(
                        f"line {line_no}: variable '{name}' changes from {existing.kind} to {kind}"
                    )
                self.symbols[name.lower()] = Symbol(name, kind)
                self.statements.append(Statement(f"{name} = {self.textscan_columns[data_name][col]}", self.indent))
                return
            textscan_call = parse_simple_call(rhs.strip())
            if textscan_call is not None and textscan_call[0].lower() == "textscan":
                if len(textscan_call[1]) < 2:
                    raise OmatError(f"line {line_no}: textscan currently requires unit and format")
                fmt = matlab_string_literal_value(textscan_call[1][1])
                if fmt != "%s %f":
                    raise OmatError(f"line {line_no}: textscan currently supports format \"%s %f\"")
                self.symbols[name.lower()] = Symbol(name, "textscan")
                self.textscan_units[name.lower()] = self.expr(textscan_call[1][0])
                labels_name = f"omat_{name}_col1"
                values_name = f"omat_{name}_col2"
                self.symbols[labels_name.lower()] = Symbol(labels_name, "string_vector")
                self.symbols[values_name.lower()] = Symbol(values_name, "real_vector")
                self.textscan_columns[name.lower()] = {1: labels_name, 2: values_name}
                self.statements.append(
                    Statement(
                        f"call read_textscan_string_real_omat({self.textscan_units[name.lower()]}, {labels_name}, {values_name})",
                        self.indent,
                    )
                )
                return
            fopen_call = parse_simple_call(rhs.strip())
            if fopen_call is not None and fopen_call[0].lower() == "fopen":
                if len(fopen_call[1]) < 2:
                    raise OmatError(f"line {line_no}: fopen currently requires filename and mode")
                mode = matlab_string_literal_value(fopen_call[1][1].strip())
                if mode is None:
                    raise OmatError(f"line {line_no}: fopen mode must be a literal string")
                file_expr = self.expr(fopen_call[1][0])
                existing = self.symbols.get(name.lower())
                if existing is not None and existing.kind != "integer":
                    raise OmatError(
                        f"line {line_no}: variable '{name}' changes from {existing.kind} to integer"
                    )
                self.symbols[name.lower()] = Symbol(name, "integer")
                if mode.startswith("w"):
                    self.statements.append(
                        Statement(
                            f"open(newunit={name}, file=trim({file_expr}), status='replace', action='write')",
                            self.indent,
                        )
                    )
                elif mode.startswith("r"):
                    self.statements.append(
                        Statement(
                            f"open(newunit={name}, file=trim({file_expr}), status='old', action='read')",
                            self.indent,
                        )
                    )
                else:
                    raise OmatError(f"line {line_no}: fopen mode '{mode}' is not implemented yet")
                return
            fgetl_call = parse_simple_call(rhs.strip())
            if fgetl_call is not None and fgetl_call[0].lower() == "fgetl" and len(fgetl_call[1]) == 1:
                existing = self.symbols.get(name.lower())
                if existing is not None and existing.kind != "string":
                    raise OmatError(
                        f"line {line_no}: variable '{name}' changes from {existing.kind} to string"
                    )
                self.symbols[name.lower()] = Symbol(name, "string")
                self.statements.append(Statement(f"read({self.expr(fgetl_call[1][0])}, '(a)') {name}", self.indent))
                return
            kind = self.const_kind(rhs) if const_directive else self.infer_kind(rhs)
            existing = self.symbols.get(name.lower())
            if existing is not None and existing.constant:
                raise OmatError(f"line {line_no}: cannot assign to constant '{name}'")
            if existing is not None and existing.kind != kind:
                raise OmatError(
                    f"line {line_no}: variable '{name}' changes from {existing.kind} to {kind}"
                )
            value = self.expr(rhs)
            self.symbols[name.lower()] = Symbol(name, kind, constant=const_directive, value=value if const_directive else None)
            if not const_directive:
                self.statements.append(Statement(f"{name} = {value}", self.indent))
            if not suppress_output:
                self.statements.append(Statement(self.display_statement(name, kind), self.indent))
            return

        if const_directive:
            raise OmatError(f"line {line_no}: % omat: const must be used on an assignment")

        multi = MULTI_ASSIGN_RE.match(line)
        if multi:
            left_name, right_name, rhs = multi.groups()
            call = parse_simple_call(rhs.strip().lower())
            if call is None or call[0] != "eig" or len(call[1]) != 1:
                raise OmatError(f"line {line_no}: multi-output assignment currently supports [V,D] = eig(A)")
            self.symbols[left_name.lower()] = Symbol(left_name, "real_matrix")
            self.symbols[right_name.lower()] = Symbol(right_name, "real_matrix")
            arg = self.expr(call[1][0])
            self.statements.append(Statement(f"{left_name} = eigvecs_omat({arg})", self.indent))
            self.statements.append(Statement(f"{right_name} = diag_vec_omat(eigvals_omat({arg}))", self.indent))
            return

        if not suppress_output:
            self.emit_display(line)

    def const_kind(self, rhs: str) -> str:
        kind = self.infer_kind(rhs)
        if kind.endswith("_vector") or kind.endswith("_matrix"):
            raise OmatError("% omat: const currently supports scalar constants only")
        if kind == "integer" or is_typed_integer_kind(kind) or self.is_logical_expr(rhs):
            pass
        elif is_integer_expr(rhs, self.symbols):
            kind = "integer"
        elif kind != "real":
            raise OmatError("% omat: const currently supports scalar numeric and logical constants only")
        names = [
            name for name in IDENT_RE.findall(rhs)
            if name.lower() not in {"true", "false", "int8", "int16", "int32", "int64"}
        ]
        for name in names:
            if identifier_is_indexed(rhs, name):
                continue
            sym = self.symbols.get(name.lower())
            if sym is None or not sym.constant:
                raise OmatError("% omat: const RHS must be a scalar constant expression")
        return kind

    def parse_logical_index_assignment(self, line: str) -> tuple[str, str, str] | None:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*=\s*(.+)$", line)
        if not m:
            return None
        name, index, rhs = m.groups()
        sym = self.symbols.get(name.lower())
        if sym is None or sym.kind not in {"real_vector", "real_matrix", "integer_vector", "logical_vector", "logical_matrix"}:
            return None
        args = split_args(index)
        if len(args) != 1 or not self.is_logical_selector(args[0]):
            return None
        rhs_kind = self.infer_kind(rhs)
        if rhs_kind.endswith("_vector") or rhs_kind.endswith("_matrix"):
            raise OmatError("logical-index assignment currently requires a scalar right-hand side")
        return name, self.expr(args[0]), self.expr(rhs)

    def emit_display(self, value: str) -> None:
        stripped = value.strip()
        kind = self.infer_kind(stripped)
        self.statements.append(Statement(self.display_statement(self.expr(stripped), kind), self.indent))

    def fprintf_statement(self, args: list[str], line_no: int) -> str:
        if not args:
            raise OmatError(f"line {line_no}: fprintf requires a format string")
        unit_expr = "*"
        fmt_index = 0
        if len(args) >= 2 and matlab_string_literal_value(args[0]) is None:
            unit_expr = self.expr(args[0])
            fmt_index = 1
        fmt = matlab_string_literal_value(args[fmt_index])
        if fmt is None:
            raise OmatError(f"line {line_no}: fprintf currently requires a literal format string")
        descriptors, format_args, n_conversions, newline = matlab_fprintf_format(fmt)
        actuals = [self.expr(arg) for arg in args[fmt_index + 1 :]]
        if len(actuals) != n_conversions:
            raise OmatError(
                f"line {line_no}: fprintf format expects {n_conversions} argument"
                f"{'' if n_conversions == 1 else 's'}, got {len(actuals)}"
        )
        actual_iter = iter(actuals)
        write_args = []
        write_descriptors = []
        for item, descriptor in zip(format_args, descriptors):
            if item == "__format_only__":
                write_descriptors.append(descriptor)
                continue
            if item is not None:
                write_descriptors.append(descriptor)
                write_args.append(item)
                continue
            actual = next(actual_iter)
            if descriptor.startswith("__fixed_"):
                width, precision = descriptor.removeprefix("__fixed_").split("_", 1)
                actual = f"trim(adjustl(fixed_text_omat({actual}, {precision})))"
                descriptor = f"a{width}" if width != "0" else "a"
            elif descriptor.startswith("__exp_"):
                width, precision = descriptor.removeprefix("__exp_").split("_", 1)
                actual = f"trim(adjustl(exp_text_omat({actual}, {precision})))"
                descriptor = f"a{width}" if width != "0" else "a"
            elif descriptor.lower().startswith("i"):
                actual = f"int({actual})"
            elif descriptor.lower().startswith("a"):
                actual = f"trim({actual})"
            write_descriptors.append(descriptor)
            write_args.append(actual)
        fmt_literal = fortran_string_literal("(" + ",".join(write_descriptors) + ")")
        suffix = "" if newline else ", advance='no'"
        if write_args:
            return f"write({unit_expr},{fmt_literal}{suffix}) {', '.join(write_args)}"
        return f"write({unit_expr},{fmt_literal}{suffix})"

    def display_statement(self, expr: str, kind: str) -> str:
        if kind == "real_matrix":
            return f"call print_real_matrix_omat({expr})"
        if kind == "real_vector":
            return f'print "(*(f0.8,:,1x))", {expr}'
        if kind == "integer_vector":
            return f'print "(*(i0,:,1x))", {expr}'
        if is_typed_integer_vector_kind(kind):
            return f'print "(*(i0,:,1x))", {expr}'
        if kind == "logical_vector":
            return f"call {'disp_omat' if self.generic else 'print_logical_vector_omat'}({expr})"
        if kind == "logical_matrix":
            return f"call print_logical_matrix_omat({expr})"
        if kind == "integer":
            return f'print "(i0)", {expr}'
        if is_typed_integer_kind(kind):
            return f'print "(i0)", {expr}'
        if kind == "logical":
            return f"call print_logical_scalar_omat({expr})"
        return f'print "(f0.8)", {expr}'

    def infer_kind(self, rhs: str) -> str:
        low = rhs.strip().lower()
        if is_flatten_expr(low):
            return "real_vector"
        indexed = self.indexed_expr_kind(low)
        if indexed is not None:
            return indexed
        call = parse_simple_call(low)
        if call is not None:
            name, args = call
            if self.ensure_local_function(name):
                return self.register_local_function_call(name, args)
            if name == "size":
                if len(args) == 1:
                    return "integer_vector"
                return "integer"
            if name in {"length", "numel"}:
                return "integer"
            if name in {"any", "all"}:
                return "logical"
            if name == "exist":
                return "logical"
            if name in {"isvector", "ismatrix", "isscalar", "isempty"}:
                return "logical"
            if name == "find":
                return "integer_vector"
            if name in {"unique", "intersect", "union", "setdiff", "nonzeros"}:
                return "real_vector"
            if name == "ismember":
                return "logical_vector"
            if name in {"isnan", "isfinite", "isinf"}:
                return "logical_vector"
            if name in {"diff", "sort"}:
                return "real_vector"
            if name == "randi":
                if len(args) == 1:
                    return "integer"
                if len(args) in {2, 3}:
                    return "integer_vector" if len(args) == 2 or args[2].strip() == "1" else "real_matrix"
                raise OmatError("randi currently supports randi(imax), randi([imin,imax],n), and randi([imin,imax],n,1)")
            if name in INTEGER_CONSTRUCTORS and args:
                if len(args) != 1:
                    raise OmatError(f"{name} currently supports one argument")
                arg = args[0].strip()
                if is_vector_expr(arg.lower()):
                    return f"integer_{name}_vector"
                return f"integer_{name}"
            if name == "normcdf" and args:
                sym = self.symbols.get(args[0].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_matrix"
                if sym is not None and sym.kind == "real_vector":
                    return "real_vector"
                if is_matrix_expr(args[0].strip().lower()):
                    return "real_matrix"
                if is_vector_expr(args[0].strip().lower()):
                    return "real_vector"
                return "real"
            if name == "logspace":
                return "real_vector"
            if name in {"floor", "ceil", "round", "fix", "sign", "flip", "fliplr", "flipud"} and args:
                sym = self.symbols.get(args[0].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_matrix"
                if sym is not None and sym.kind == "real_vector":
                    return "real_vector"
                if is_matrix_expr(args[0].strip().lower()):
                    return "real_matrix"
                if is_vector_expr(args[0].strip().lower()):
                    return "real_vector"
                return "real"
            if name == "mod" and args:
                saw_integer_vector = False
                for arg in args:
                    sym = self.symbols.get(arg.strip().lower())
                    if sym is not None and sym.kind == "real_matrix":
                        return "real_matrix"
                    if sym is not None and sym.kind == "real_vector":
                        return "real_vector"
                    if sym is not None and sym.kind == "integer_vector":
                        saw_integer_vector = True
                if saw_integer_vector:
                    return "integer_vector"
                return "real"
            if name == "transpose" and args:
                sym = self.symbols.get(args[0].strip().lower())
                if sym is not None and sym.kind == "real_vector":
                    return "real_matrix"
                if sym is not None and sym.kind == "real_matrix":
                    return "real_matrix"
                if is_vector_expr(args[0].strip().lower()) or is_matrix_expr(args[0].strip().lower()):
                    return "real_matrix"
                return "real"
            if name == "eye":
                return "real_matrix"
            if name == "diag" and args:
                sym = self.symbols.get(args[0].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_vector"
                return "real_matrix"
            if name == "repmat":
                return "real_matrix"
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
            if name in {"solve", "mldivide"} and len(args) >= 2:
                sym = self.symbols.get(args[1].strip().lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_matrix"
                return "real_vector"
        if split_top_level_backslash(rhs) is not None:
            return "real_vector"
        if matlab_string_literal_value(rhs) is not None:
            return "string"
        if self.horizontal_matrix_concat_items(rhs) is not None:
            return "real_matrix"
        if contains_vector_randi_call(rhs):
            return "real_vector"
        if is_matrix_expr(low):
            return "real_matrix"
        if is_vector_expr(low):
            return self.vector_expr_kind(rhs)
        if self.is_logical_expr(rhs):
            return self.logical_expr_kind(rhs)
        if re.match(r"^(sum|min|max|prod)\s*\(.+\)$", low, re.IGNORECASE):
            args = split_args(low[low.find("(") + 1 : -1])
            if args:
                sym = self.symbols.get(args[0].lower())
                if sym is not None and sym.kind == "real_matrix":
                    return "real_vector"
            return "real"
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
        whole_symbol = self.symbols.get(rhs.strip().lower())
        if whole_symbol is not None:
            return whole_symbol.kind
        expr_kind = self.expression_container_kind(rhs)
        if expr_kind is not None:
            return expr_kind
        for name in IDENT_RE.findall(rhs):
            if identifier_is_indexed(rhs, name):
                continue
            if identifier_only_occurs_as_argument_to_scalar_function(rhs, name):
                continue
            sym = self.symbols.get(name.lower())
            if sym is not None and rhs.strip().lower() == name.lower():
                return sym.kind
            if sym is not None and (
                sym.kind in {"real_vector", "integer_vector", "logical_vector"}
                or is_typed_integer_vector_kind(sym.kind)
            ):
                return sym.kind
        if rhs.strip().lower() == "pi":
            return "real"
        if is_integer_declaration_expr(rhs, self.symbols):
            return "integer"
        if is_typed_integer_expr(rhs, self.symbols):
            return "integer"
        return "real"

    def expression_container_kind(self, rhs: str) -> str | None:
        saw_vector = False
        for name in IDENT_RE.findall(rhs):
            if identifier_only_occurs_as_argument_to_scalar_function(rhs, name):
                continue
            sym = self.symbols.get(name.lower())
            if sym is None:
                continue
            if sym.kind == "real_matrix":
                return "real_matrix"
            if sym.kind in {"real_vector", "integer_vector", "logical_vector"} or is_typed_integer_vector_kind(sym.kind):
                saw_vector = True
        return "real_vector" if saw_vector else None

    def register_local_function_call(self, name: str, args: list[str]) -> str:
        func = self.local_functions[name]
        if len(args) != len(func.args):
            raise OmatError(f"function '{func.name}' expects {len(func.args)} arguments")
        arg_kinds = [self.argument_kind(arg.strip()) for arg in args]
        result_kind = "real"
        if any(kind.endswith("_matrix") for kind in arg_kinds):
            result_kind = "real_matrix"
        elif any(kind.endswith("_vector") for kind in arg_kinds):
            result_kind = "real_vector"
        existing = self.local_function_signatures.get(name)
        signature = (arg_kinds, result_kind)
        if existing is not None and existing != signature:
            raise OmatError(f"function '{func.name}' is called with inconsistent argument shapes")
        self.local_function_signatures[name] = signature
        return result_kind

    def ensure_local_function(self, name: str) -> bool:
        lname = name.lower()
        if lname in self.local_functions:
            return True
        if is_known_function_name(lname) or self.function_search_dir is None:
            return False
        path = find_function_file(self.function_search_dir, lname)
        if path is None:
            return False
        if lname in self.loading_functions:
            raise OmatError(f"recursive function-file load for '{name}'")
        self.loading_functions.add(lname)
        try:
            func = read_function_file(path)
        finally:
            self.loading_functions.remove(lname)
        if func.name.lower() != lname:
            raise OmatError(
                f"function file '{path.name}' defines '{func.name}', expected '{path.stem}'"
            )
        self.local_functions[lname] = func
        return True

    def indexed_expr_kind(self, text: str) -> str | None:
        parsed = parse_index_expr(text)
        if parsed is None:
            return None
        name, args = parsed
        sym = self.symbols.get(name.lower())
        if sym is None:
            return None
        if sym.kind in {"real_vector", "integer_vector", "logical_vector", "string_vector"}:
            if len(args) != 1:
                return None
            if self.is_logical_selector(args[0]):
                return sym.kind
            if sym.kind == "string_vector":
                return sym.kind if index_selects_many(args[0]) else "string"
            return sym.kind if index_selects_many(args[0]) else vector_element_kind(sym.kind)
        if sym.kind in {"real_matrix", "logical_matrix"}:
            if len(args) == 1:
                if self.is_logical_selector(args[0]):
                    return "real_vector" if sym.kind == "real_matrix" else "logical_vector"
                return "real_vector" if sym.kind == "real_matrix" else "logical_vector"
            if len(args) != 2:
                return None
            row_many = index_selects_many(args[0])
            col_many = index_selects_many(args[1])
            if row_many and col_many:
                return sym.kind
            if row_many or col_many:
                return "real_vector" if sym.kind == "real_matrix" else "logical_vector"
            return "real" if sym.kind == "real_matrix" else "logical"
        return None

    def vector_expr_kind(self, rhs: str) -> str:
        text = rhs.strip()
        if not (text.startswith("[") and text.endswith("]") and ";" not in text):
            return "real_vector"
        items = split_matlab_literal_row(text[1:-1].strip())
        kinds = [self.infer_kind(item) for item in items]
        typed_integer_scalars = [kind for kind in kinds if is_typed_integer_kind(kind)]
        if typed_integer_scalars and all(kind == typed_integer_scalars[0] for kind in kinds):
            return typed_integer_scalars[0] + "_vector"
        if (
            kinds
            and all(kind == "integer" for kind in kinds)
            and not all(is_integer_numeric_literal(item) for item in items)
        ):
            return "integer_vector"
        if kinds and all(kind in {"logical", "logical_vector"} for kind in kinds):
            return "logical_vector"
        return "real_vector"

    def is_logical_expr(self, rhs: str) -> bool:
        return re.search(
            r"(==|~=|<=|>=|<|>|\btrue\b|\bfalse\b|\.true\.|\.false\.)",
            rhs,
            re.IGNORECASE,
        ) is not None

    def logical_expr_kind(self, rhs: str) -> str:
        for name in IDENT_RE.findall(rhs):
            if identifier_is_indexed(rhs, name):
                continue
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
        out = self.convert_logical_indexing(out)
        out = self.convert_cell_indexing(out)
        out = self.convert_end_indices(out)
        out = self.convert_index_triplets(out)
        out = self.convert_colon_vector(out)
        out = self.convert_vertical_vector_concat(out)
        out = self.convert_horizontal_matrix_concat(out)
        out = self.convert_integer_constructors(out)
        out = convert_vector_literals(out)
        out = convert_elementwise(out)
        out = self.convert_power(out)
        out = self.convert_matrix_multiply(out)
        out = self.convert_left_divide(out)
        out = self.convert_basic_array_functions(out)
        out = self.convert_la_functions(out)
        out = self.convert_random_dist_functions(out)
        out = self.convert_stats_functions(out)
        out = self.convert_exist_function(out)
        out = self.convert_normcdf(out)
        out = self.convert_sqrt_function(out)
        out = self.convert_function_names(out)
        out = self.convert_rand(out)
        out = self.convert_randi(out)
        out = self.convert_zeros_ones(out)
        out = self.convert_equicor(out)
        out = self.convert_linspace(out)
        out = self.convert_logspace(out)
        out = convert_pi_constant(out)
        out = convert_logical_literals(out)
        out = convert_numbers(out)
        return out

    def convert_integer_constructors(self, text: str) -> str:
        out = text
        for name in sorted(INTEGER_CONSTRUCTORS):
            def repl(match: re.Match[str], name: str = name) -> str:
                args = split_args(match.group(1))
                if len(args) != 1:
                    raise OmatError(f"{name} currently supports one argument")
                self.integer_env_kinds.add(name)
                arg = args[0].strip()
                scalar_literal = integer_literal_text(arg)
                if scalar_literal is not None:
                    return f"{scalar_literal}_{name}"
                vector_literal = typed_integer_vector_literal(arg, name)
                if vector_literal is not None:
                    return vector_literal
                return f"int({self.expr(arg)}, {name})"

            out = re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, out, flags=re.IGNORECASE)
        return out

    def convert_logical_indexing(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name.lower() in BUILTINS or name.lower() in LA_FUNCTIONS or name.lower() in RANDOM_DIST_PARAM_COUNTS:
                return match.group(0)
            sym = self.symbols.get(name.lower())
            if sym is None or sym.kind not in {"real_vector", "real_matrix", "integer_vector", "logical_vector", "logical_matrix"}:
                return match.group(0)
            args = split_args(match.group(2))
            if len(args) != 1 or not self.is_logical_selector(args[0]):
                return match.group(0)
            return f"pack({name}, {self.expr(args[0])})"

        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)", repl, text)

    def convert_cell_indexing(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            index = self.expr(match.group(2))
            sym = self.symbols.get(name.lower())
            if sym is not None and sym.kind == "string_vector":
                return f"{name}({index})"
            return match.group(0)

        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*([^{}]+)\s*\}", repl, text)

    def is_logical_selector(self, text: str) -> bool:
        stripped = text.strip()
        sym = self.symbols.get(stripped.lower())
        if sym is not None and sym.kind in {"logical_vector", "logical_matrix"}:
            return True
        return self.is_logical_expr(stripped) and self.logical_expr_kind(stripped) in {
            "logical_vector",
            "logical_matrix",
        }

    def convert_end_indices(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            lname = name.lower()
            if lname in BUILTINS or lname in LA_FUNCTIONS or lname in RANDOM_DIST_PARAM_COUNTS:
                return match.group(0)
            sym = self.symbols.get(lname)
            if sym is None:
                return match.group(0)
            args = split_args(match.group(2))
            if not any(re.search(r"\bend\b", arg, re.IGNORECASE) for arg in args):
                return match.group(0)
            converted = []
            for i, arg in enumerate(args):
                if sym.kind in {"real_matrix", "logical_matrix"} and len(args) >= 2:
                    size_expr = f"ubound({name}, {i + 1})"
                else:
                    size_expr = f"ubound({name}, 1)"
                converted.append(re.sub(r"\bend\b", size_expr, arg.strip(), flags=re.IGNORECASE))
            return f"{name}({', '.join(converted)})"

        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)", repl, text)

    def convert_index_triplets(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name.lower() in BUILTINS or name.lower() in LA_FUNCTIONS or name.lower() in RANDOM_DIST_PARAM_COUNTS:
                return match.group(0)
            args = split_args(match.group(2))
            converted = []
            changed = False
            for arg in args:
                parts = split_top_level_colon(arg.strip())
                if len(parts) == 3:
                    converted.append(f"{parts[0]}:{parts[2]}:{parts[1]}")
                    changed = True
                else:
                    converted.append(arg.strip())
            if not changed:
                return match.group(0)
            return f"{name}({', '.join(converted)})"

        return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)", repl, text)

    def convert_basic_array_functions(self, text: str) -> str:
        out = text
        out = self.convert_eye(out)
        out = self.convert_diag(out)
        out = self.convert_repmat(out)
        out = self.convert_numeric_unary_functions(out)
        out = self.convert_mod_function(out)
        out = self.convert_flip_functions(out)
        out = self.convert_transpose_function(out)
        out = self.convert_size_function(out)
        out = self.convert_shape_predicates(out)
        out = self.convert_length_numel(out)
        out = self.convert_one_arg_kind_function(out, "diff", "diff_vec_omat")
        out = self.convert_one_arg_kind_function(out, "sort", "sort_vec_omat")
        out = self.convert_find_function(out)
        out = self.convert_one_arg_kind_function(out, "unique", "unique_vec_omat")
        out = self.convert_one_arg_kind_function(out, "nonzeros", "nonzeros_vec_omat")
        out = self.convert_two_arg_vector_function(out, "intersect", "intersect_vec_omat")
        out = self.convert_two_arg_vector_function(out, "union", "union_vec_omat")
        out = self.convert_two_arg_vector_function(out, "setdiff", "setdiff_vec_omat")
        out = self.convert_two_arg_vector_function(out, "ismember", "ismember_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isnan", "isnan_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isfinite", "isfinite_vec_omat")
        out = self.convert_one_arg_kind_function(out, "isinf", "isinf_vec_omat")
        out = self.convert_one_arg_kind_function(out, "any", "any_vec_omat")
        out = self.convert_one_arg_kind_function(out, "all", "all_vec_omat")
        return out

    def convert_size_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) not in {1, 2}:
                raise OmatError("size currently supports size(x) and size(x, dim)")
            arg = args[0].strip()
            expr = self.expr(arg)
            sym = self.symbols.get(arg.lower())
            kind = sym.kind if sym is not None else self.argument_kind(arg)
            if len(args) == 1:
                if kind == "real_matrix":
                    return f"[size({expr}, 1), size({expr}, 2)]"
                if kind.endswith("_vector"):
                    return f"[1, size({expr})]"
                return "[1, 1]"
            dim = self.integer_arg(args[1])
            if kind == "real_matrix":
                return f"size({expr}, {dim})"
            if kind.endswith("_vector"):
                if dim == "1":
                    return "1"
                if dim == "2":
                    return f"size({expr})"
                return "1"
            return "1"

        return re.sub(r"\bsize\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_shape_predicates(self, text: str) -> str:
        for name in ["isvector", "ismatrix", "isscalar", "isempty"]:
            text = self.convert_one_shape_predicate(text, name)
        return text

    def convert_vertical_vector_concat(self, text: str) -> str:
        stripped = text.strip()
        if not (stripped.startswith("[") and stripped.endswith("]") and ";" in stripped):
            return text
        rows = [row.strip() for row in stripped[1:-1].split(";")]
        if len(rows) < 2:
            return text
        names: list[str] = []
        for row in rows:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", row):
                return text
            sym = self.symbols.get(row.lower())
            if sym is None or sym.kind != "real_vector":
                return text
            names.append(row)
        return f"vcat_vecs_omat({', '.join(names)})"

    def horizontal_matrix_concat_items(self, text: str) -> list[str] | None:
        stripped = text.strip()
        if not (stripped.startswith("[") and stripped.endswith("]") and ";" not in stripped):
            return None
        items = split_matlab_literal_row(stripped[1:-1].strip())
        if len(items) < 2:
            return None
        saw_matrix = False
        for item in items:
            if self.matrix_concat_expr(item) is None:
                return None
            if self.argument_kind(item) == "real_matrix" or self.ones_zeros_size_matrix_expr(item) is not None:
                saw_matrix = True
        return items if saw_matrix else None

    def convert_horizontal_matrix_concat(self, text: str) -> str:
        items = self.horizontal_matrix_concat_items(text)
        if items is None:
            return text
        exprs = [self.matrix_concat_expr(item) for item in items]
        out = exprs[0]
        for expr in exprs[1:]:
            out = f"hcat_mats_omat({out}, {expr})"
        return out

    def matrix_concat_expr(self, text: str) -> str | None:
        special = self.ones_zeros_size_matrix_expr(text)
        if special is not None:
            return special
        kind = self.argument_kind(text)
        if kind == "real_matrix":
            return self.expr(text)
        if kind == "real_vector":
            expr = self.expr(text)
            return f"reshape_mat_from_vec_omat({expr}, size({expr}), 1)"
        return None

    def ones_zeros_size_matrix_expr(self, text: str) -> str | None:
        call = parse_simple_call(text.strip().lower())
        if call is None:
            return None
        name, args = call
        if name not in {"ones", "zeros"} or len(args) != 1:
            return None
        size_call = parse_simple_call(args[0].strip())
        if size_call is None or size_call[0] != "size" or len(size_call[1]) != 1:
            return None
        target = size_call[1][0].strip()
        sym = self.symbols.get(target.lower())
        if sym is None or sym.kind != "real_matrix":
            return None
        return f"{name}_omat2(size({target}, 1), size({target}, 2))"

    def convert_one_shape_predicate(self, text: str, name: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one argument")
            arg = args[0].strip()
            expr = self.expr(arg)
            sym = self.symbols.get(arg.lower())
            kind = sym.kind if sym is not None else self.argument_kind(arg)
            if name == "isscalar":
                return ".false." if kind.endswith("_vector") or kind.endswith("_matrix") else ".true."
            if name == "ismatrix":
                return ".true."
            if name == "isempty":
                if kind.endswith("_matrix") or kind.endswith("_vector"):
                    return f"size({expr}) == 0"
                return ".false."
            if kind.endswith("_vector"):
                return ".true."
            if kind.endswith("_matrix"):
                return f"(size({expr}, 1) == 1 .or. size({expr}, 2) == 1)"
            return ".true."

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_numeric_unary_functions(self, text: str) -> str:
        out = text
        for name in ["floor", "ceil", "round", "fix", "sign"]:
            out = self.convert_one_arg_shape_function(out, name)
        return out

    def convert_one_arg_shape_function(self, text: str, name: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one argument")
            arg = args[0].strip()
            expr = self.real_helper_expr(arg)
            sym = self.symbols.get(arg.lower())
            if sym is not None and sym.kind == "real_matrix":
                return f"{name}_mat_omat({expr})"
            if sym is not None and sym.kind == "real_vector":
                return f"{name}_vec_omat({expr})"
            if is_matrix_expr(arg.lower()):
                return f"{name}_mat_omat({expr})"
            if is_vector_expr(arg.lower()):
                return f"{name}_vec_omat({expr})"
            if name == "ceil":
                return f"real(ceiling({expr}), real64)"
            if name == "round":
                return f"anint({expr})"
            if name == "fix":
                return f"aint({expr})"
            if name == "sign":
                return f"merge(1.0_real64, merge(-1.0_real64, 0.0_real64, {expr} < 0.0_real64), {expr} > 0.0_real64)"
            return f"real(floor({expr}), real64)"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_mod_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError("mod currently supports two arguments")
            lhs = args[0].strip()
            rhs = args[1].strip()
            lhs_sym = self.symbols.get(lhs.lower())
            rhs_sym = self.symbols.get(rhs.lower())
            lhs_expr = self.expr(lhs)
            rhs_expr = self.expr(rhs)
            if (
                (lhs_sym is not None and lhs_sym.kind in {"real_vector", "real_matrix"})
                or (rhs_sym is not None and rhs_sym.kind in {"real_vector", "real_matrix"})
            ):
                if rhs_sym is None:
                    rhs_expr = f"real({rhs_expr}, real64)"
                if lhs_sym is None:
                    lhs_expr = f"real({lhs_expr}, real64)"
            return f"mod({lhs_expr}, {rhs_expr})"

        return re.sub(r"\bmod\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_flip_functions(self, text: str) -> str:
        out = text
        out = self.convert_flip_like_function(out, "fliplr")
        out = self.convert_flip_like_function(out, "flipud")
        out = self.convert_flip_like_function(out, "flip")
        return out

    def convert_flip_like_function(self, text: str, name: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError(f"{name} currently supports one argument")
            arg = args[0].strip()
            expr = self.real_helper_expr(arg)
            sym = self.symbols.get(arg.lower())
            if sym is not None and sym.kind == "real_matrix":
                helper = "fliplr_mat_omat" if name == "fliplr" else "flipud_mat_omat"
                if name == "flip":
                    helper = "flip_mat_omat"
                return f"{helper}({expr})"
            if is_matrix_expr(arg.lower()):
                helper = "fliplr_mat_omat" if name == "fliplr" else "flipud_mat_omat"
                if name == "flip":
                    helper = "flip_mat_omat"
                return f"{helper}({expr})"
            if name != "flip" and not is_matrix_expr(arg.lower()):
                raise OmatError(f"{name} currently requires a matrix argument")
            return f"flip_vec_omat({expr})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_transpose_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError("transpose currently supports one argument")
            arg = args[0].strip()
            expr = self.real_helper_expr(arg)
            sym = self.symbols.get(arg.lower())
            if sym is not None and sym.kind == "real_vector":
                return f"transpose_vec_omat({expr})"
            if sym is not None and sym.kind == "real_matrix":
                return f"transpose_mat_omat({expr})"
            if is_vector_expr(arg.lower()):
                return f"transpose_vec_omat({expr})"
            if is_matrix_expr(arg.lower()):
                return f"transpose_mat_omat({expr})"
            return expr

        return re.sub(r"\btranspose\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def real_helper_expr(self, arg: str) -> str:
        expr = self.expr(arg)
        sym = self.symbols.get(arg.strip().lower())
        if sym is not None:
            if sym.kind == "integer_vector":
                return f"real({expr}, real64)"
            return expr
        low = arg.strip().lower()
        if is_vector_expr(low) or is_matrix_expr(low):
            return f"real({expr}, real64)"
        return expr

    def convert_eye(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"eye_omat({self.integer_arg(args[0])}, {self.integer_arg(args[0])})"
            if len(args) == 2:
                return f"eye_omat({self.integer_arg(args[0])}, {self.integer_arg(args[1])})"
            raise OmatError("eye currently supports eye(n) and eye(m,n)")

        return re.sub(r"\beye\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_diag(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError("diag currently supports one argument")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            helper = "diag_mat_omat" if sym is not None and sym.kind == "real_matrix" else "diag_vec_omat"
            return f"{helper}({self.expr(arg)})"

        return re.sub(r"\bdiag\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_repmat(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 3:
                raise OmatError("repmat currently supports repmat(x,m,n)")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            helper = "repmat_mat_omat" if sym is not None and sym.kind == "real_matrix" else "repmat_vec_omat"
            return f"{helper}({self.expr(arg)}, {self.integer_arg(args[1])}, {self.integer_arg(args[2])})"

        return re.sub(r"\brepmat\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

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

    def convert_two_arg_vector_function(self, text: str, name: str, helper: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 2:
                raise OmatError(f"{name} currently supports two vector arguments")
            return f"{helper}({self.expr(args[0])}, {self.expr(args[1])})"

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_find_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"find_vec_omat({self.expr(args[0])})"
            if len(args) == 2:
                return f"find_k_vec_omat({self.expr(args[0])}, {self.integer_arg(args[1])})"
            raise OmatError("find currently supports find(mask) and find(mask,k)")

        return re.sub(r"\bfind\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_exist_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"exist_file_omat({self.expr(args[0])})"
            if len(args) == 2 and matlab_string_literal_value(args[1].strip()) == "file":
                return f"exist_file_omat({self.expr(args[0])})"
            raise OmatError("exist currently supports exist(name,'file')")

        return re.sub(r"\bexist\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

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

    def convert_left_divide(self, text: str) -> str:
        parts = split_top_level_backslash(text)
        if parts is None:
            return text
        left, right = parts
        right_expr = self.expr(right)
        right_sym = self.symbols.get(right.strip().lower())
        if right_sym is not None and right_sym.kind == "real_matrix":
            right_expr = f"{right_expr}(:, 1)"
        return f"mldivide_omat({self.expr(left)}, {right_expr})"

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
        out = self.convert_reduction(out, "sum", "sum")
        out = self.convert_reduction(out, "prod", "prod")
        out = self.convert_reduction(out, "min", "min")
        out = self.convert_reduction(out, "max", "max")
        return out

    def convert_reduction(self, text: str, name: str, helper_base: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if not args:
                raise OmatError(f"{name} requires an argument")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            if sym is None or sym.kind != "real_matrix":
                if len(args) == 1:
                    if name == "prod":
                        return f"prod_vec_omat({self.expr(arg)})"
                    if name == "min":
                        return f"min_vec_omat({self.expr(arg)})"
                    if name == "max":
                        return f"max_vec_omat({self.expr(arg)})"
                    return match.group(0)
                raise OmatError(f"{name} currently supports one argument for vectors")
            farg = self.expr(arg)
            if len(args) == 1:
                if name == "sum":
                    return f"sum({farg}, dim=1)"
                return f"{helper_base}_mat_omat({farg})"
            if len(args) == 2 and args[1].strip() in {"1", "2"}:
                if name == "sum":
                    return f"sum({farg}, dim={args[1].strip()})"
                if name in {"min", "max"}:
                    raise OmatError(
                        f"{name}(A,2) is element-wise in MATLAB/Octave; use {name}(A,[],2) for row-wise reduction"
                    )
                if args[1].strip() == "1":
                    return f"{helper_base}_mat_omat({farg})"
                if name == "prod":
                    return f"product({farg}, dim=2)"
            if name in {"min", "max"} and len(args) == 3 and args[1].strip() == "[]" and args[2].strip() in {"1", "2"}:
                if args[2].strip() == "1":
                    return f"{helper_base}_mat_omat({farg})"
                return f"{'minval' if name == 'min' else 'maxval'}({farg}, dim=2)"
            raise OmatError(
                f"matrix {name} currently supports {name}(A), {name}(A,1),"
                f" {name}(A,2) for sum/prod, and {name}(A,[],dim) for min/max"
            )

        return re.sub(rf"\b{name}\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_stats_functions(self, text: str) -> str:
        out = text
        for name in ["mean", "std", "var", "median", "skewness", "kurtosis", "rms", "mad", "iqr", "cumsum", "cumprod", "zscore"]:
            out = self.convert_one_stats_function(out, name)
        out = self.convert_quantile_function(out, "quantile", "quantile")
        out = self.convert_quantile_function(out, "prctile", "prctile")
        out = self.convert_movmean_function(out)
        out = self.convert_cumtrapz_function(out)
        out = self.convert_binary_vector_function(out, "corr", "corr_omat")
        out = self.convert_binary_vector_function(out, "trapz", "trapz_omat")
        out = self.convert_matrix_stats_function(out, "cov", "cov_omat")
        out = self.convert_matrix_stats_function(out, "corrcoef", "corrcoef_omat")
        return out

    def convert_normcdf(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) != 1:
                raise OmatError("normcdf currently supports one argument")
            arg = self.expr(args[0])
            return f"(0.5_real64 * (1.0_real64 + erf(({arg}) / sqrt(2.0_real64))))"

        return re.sub(r"\bnormcdf\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_sqrt_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            arg = match.group(1).strip()
            converted = self.expr(arg)
            if is_integer_expr(arg, self.symbols):
                return f"sqrt(real({converted}, real64))"
            return f"sqrt({converted})"

        return re.sub(r"\bsqrt\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_one_stats_function(self, text: str, name: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) not in {1, 2, 3}:
                raise OmatError(f"{name} currently supports one argument, or a matrix with dim=1/2")
            arg = args[0].strip()
            sym = self.symbols.get(arg.lower())
            if name == "mean" and sym is not None and sym.kind == "logical_vector":
                expr = self.expr(arg)
                return f"(real(count({expr}), real64) / real(size({expr}), real64))"
            suffix = "mat" if sym is not None and sym.kind == "real_matrix" else "vec"
            if len(args) == 2:
                if sym is None or sym.kind != "real_matrix" or args[1].strip() not in {"1", "2"}:
                    raise OmatError(f"{name} currently supports dim only for matrices, with dim 1 or 2")
                if name == "std":
                    raise OmatError("std(A,2) sets the normalization in MATLAB/Octave; use std(A,0,2) for row-wise standard deviation")
                if args[1].strip() == "2":
                    if name not in {"mean", "std"}:
                        raise OmatError(f"{name}(A,2) is not implemented yet")
                    return f"{name}_mat_dim2_omat({self.expr(arg)})"
            if len(args) == 3:
                if name != "std":
                    raise OmatError(f"{name} currently supports dim as a second argument only")
                if sym is None or sym.kind != "real_matrix" or args[1].strip() != "0" or args[2].strip() not in {"1", "2"}:
                    raise OmatError("std currently supports std(A,0,1) and std(A,0,2)")
                if args[2].strip() == "2":
                    return f"std_mat_dim2_omat({self.expr(arg)})"
                return f"std_mat_omat({self.expr(arg)})"
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

    def convert_cumtrapz_function(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if len(args) == 1:
                return f"cumtrapz_vec_omat({self.expr(args[0])})"
            if len(args) == 2:
                return f"cumtrapz_xy_omat({self.expr(args[0])}, {self.expr(args[1])})"
            raise OmatError("cumtrapz currently supports cumtrapz(y) and cumtrapz(x,y)")

        return re.sub(r"\bcumtrapz\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

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
                return f"reshape_vec_from_mat_omat({name}, size({name}, 1) * size({name}, 2))"
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

    def argument_kind(self, text: str) -> str:
        low = text.strip().lower()
        sym = self.symbols.get(low)
        if sym is not None:
            return sym.kind
        if is_matrix_expr(low):
            return "real_matrix"
        if is_vector_expr(low):
            return "real_vector"
        return "real"

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

    def convert_randi(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            args = split_args(match.group(1))
            if not args:
                raise OmatError("randi requires bounds")
            bounds = shape_literal_args(args[0])
            if bounds is None:
                imin = "1"
                imax = self.integer_arg(args[0])
            elif len(bounds) == 2:
                imin = self.integer_arg(bounds[0])
                imax = self.integer_arg(bounds[1])
            else:
                raise OmatError("randi bounds must be imax or [imin, imax]")
            if len(args) == 1:
                return f"randi_scalar_omat({imin}, {imax})"
            if len(args) == 2:
                return f"randi_vec_omat({imin}, {imax}, {self.integer_arg(args[1])})"
            if len(args) == 3 and args[2].strip() == "1":
                return f"randi_vec_omat({imin}, {imax}, {self.integer_arg(args[1])})"
            raise OmatError("randi currently supports randi(imax), randi([imin,imax],n), and randi([imin,imax],n,1)")

        return re.sub(r"\brandi\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

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

    def convert_logspace(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            self.needs_linstep = True
            args = split_args(match.group(1))
            if len(args) == 2:
                args.append("50")
            if len(args) != 3:
                raise OmatError("logspace requires two or three arguments")
            return (
                f"logspace_omat(real({self.expr(args[0])}, real64), "
                f"real({self.expr(args[1])}, real64), {self.integer_arg(args[2])})"
            )

        return re.sub(r"\blogspace\s*\(([^()]*)\)", repl, text, flags=re.IGNORECASE)

    def convert_colon_vector(self, text: str) -> str:
        stripped = text.strip()
        parts = split_top_level_colon(stripped)
        if len(parts) == 2:
            self.needs_linstep = True
            return (
                f"colon2_omat(real({self.expr(parts[0])}, real64), "
                f"real({self.expr(parts[1])}, real64))"
            )
        if len(parts) == 3:
            self.needs_linstep = True
            return (
                f"colon3_omat(real({self.expr(parts[0])}, real64), "
                f"real({self.expr(parts[1])}, real64), "
                f"real({self.expr(parts[2])}, real64))"
            )
        return text

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
        user_function_lines = self.emit_local_function_lines()
        helper_lines: list[str] = []
        helper_public_names: list[str] = []
        helper_scan_lines = body_lines + user_function_lines
        if any(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*_omat[0-9]*\s*\(", line) for line in helper_scan_lines):
            helper_lines = helper_source(self.needs_linstep, helper_scan_lines, use_generic_print=self.generic)
            helper_public_names = [name for name, _ in split_helper_blocks(helper_lines)]
        main_uses_print_vector = self.generic and any(re.search(r"\bdisp_omat\s*\(", line) for line in body_lines)
        needs_print_vector_interface = self.generic and (main_uses_print_vector or any(
            re.search(r"\bprint_vector_omat\s*\(", line) for line in helper_lines
        ))
        vector_print_specifics = {
            "print_real_vector_omat",
            "print_integer_vector_omat",
            "print_logical_vector_omat",
        }
        public_helper_names = helper_public_names.copy()
        if needs_print_vector_interface:
            public_helper_names = [name for name in public_helper_names if name not in vector_print_specifics]
        if main_uses_print_vector and "disp_omat" not in public_helper_names:
            public_helper_names.insert(0, "disp_omat")
        main_helper_names = direct_helper_names(body_lines, public_helper_names)
        local_function_use_names = [
            func.name for name, func in self.local_functions.items()
            if re.search(rf"\b{re.escape(func.name)}\s*\(", "\n".join(body_lines))
        ]
        main_needs_kind_alias = self.main_needs_kind_alias(body_lines)
        main_use_names = main_helper_names.copy()
        for name in local_function_use_names:
            if name not in main_use_names:
                main_use_names.append(name)
        module_public_names = main_use_names.copy()
        module_needed = bool(helper_lines or user_function_lines or needs_print_vector_interface)
        module_body_text = "\n".join(helper_lines + user_function_lines)

        lines: list[str] = []
        if self.generic and self.random_names:
            lines.extend(generic_random_module_source(sorted(self.random_names), self.random_specific_names))
            lines.append("")
        if module_needed:
            module_iso_names: list[str] = []
            if "real64" in module_body_text:
                module_iso_names.append(f"{kind_alias} => real64")
            for name in sorted(self.integer_env_kinds):
                if re.search(rf"\b{re.escape(name)}\b", module_body_text):
                    module_iso_names.append(name)
            lines.append("module m_mod")
            if module_iso_names:
                lines.append("use, intrinsic :: iso_fortran_env, only: " + ", ".join(module_iso_names))
            lines.append("implicit none")
            lines.append("private")
            if module_public_names:
                lines.append("public :: " + ", ".join(module_public_names))
            if needs_print_vector_interface:
                lines.append("interface print_vector_omat")
                lines.append("  module procedure print_real_vector_omat, print_integer_vector_omat, print_logical_vector_omat")
                lines.append("end interface print_vector_omat")
            if helper_lines:
                lines.append("contains")
                lines.extend(helper_lines)
                if user_function_lines:
                    lines.append("")
                    lines.extend(user_function_lines)
            elif user_function_lines:
                lines.append("contains")
                lines.extend(user_function_lines)
            lines.append("end module m_mod")
            lines.append("")
        lines.append("program omat_main")
        main_iso_names: list[str] = []
        if main_needs_kind_alias:
            main_iso_names.append(f"{kind_alias} => real64")
        main_iso_names.extend(sorted(self.integer_env_kinds))
        if main_iso_names:
            lines.append("use, intrinsic :: iso_fortran_env, only: " + ", ".join(main_iso_names))
        if module_needed and main_use_names:
            lines.append("use m_mod, only: " + ", ".join(main_use_names))
        if self.needs_la_mod:
            names = sorted(self.la_names)
            lines.append("use ofort_la_mod, only: " + ", ".join(names))
        if self.needs_random_mod:
            names = sorted(self.random_names)
            module_name = "random_mod" if self.generic else "ofort_random_mod"
            lines.append(f"use {module_name}, only: " + ", ".join(names))
        lines.append("implicit none")
        for sym in self.symbols.values():
            if sym.constant:
                lines.append(parameter_declaration(sym))
            elif sym.kind == "integer":
                lines.append(f"integer :: {sym.name}")
            elif is_typed_integer_kind(sym.kind):
                lines.append(f"integer({typed_integer_env_kind(sym.kind)}) :: {sym.name}")
            elif sym.kind == "logical":
                lines.append(f"logical :: {sym.name}")
            elif sym.kind == "string":
                lines.append(f"character(len=256) :: {sym.name}")
            elif sym.kind == "string_vector":
                lines.append(f"character(len=256), allocatable :: {sym.name}(:)")
            elif sym.kind == "textscan":
                pass
            elif sym.kind == "integer_vector":
                lines.append(f"integer, allocatable :: {sym.name}(:)")
            elif is_typed_integer_vector_kind(sym.kind):
                lines.append(
                    f"integer({typed_integer_env_kind(sym.kind)}), allocatable :: {sym.name}(:)"
                )
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
        lines = coalesce_fortran_declarations(lines)
        return wrap_fortran_source(self.apply_real64_alias(lines, kind_alias)) + "\n"

    def main_needs_kind_alias(self, body_lines: list[str]) -> bool:
        if any(sym.kind in {"real", "real_vector", "real_matrix"} for sym in self.symbols.values()):
            return True
        return any("real64" in line for line in body_lines)

    def emit_local_function_lines(self) -> list[str]:
        out: list[str] = []
        emitted: set[str] = set()
        while True:
            pending = [
                (name, func)
                for name, func in list(self.local_functions.items())
                if name not in emitted
            ]
            if not pending:
                break
            name, func = pending[0]
            arg_kinds, result_kind = self.local_function_signatures.get(
                name,
                (["real"] * len(func.args), "real"),
            )
            translator = Translator(generic=self.generic)
            translator.function_search_dir = self.function_search_dir
            translator.loading_functions = self.loading_functions
            translator.local_functions = self.local_functions
            translator.local_function_signatures = self.local_function_signatures
            translator.needs_linstep = self.needs_linstep
            for arg, kind in zip(func.args, arg_kinds):
                translator.symbols[arg.lower()] = Symbol(arg, kind)
            translator.symbols[func.result.lower()] = Symbol(func.result, result_kind)
            for line_no, raw in func.body:
                text = strip_comment(raw).strip()
                if ASSIGN_RE.match(text) and not text.endswith(";"):
                    raw = raw.rstrip() + ";"
                translator.add_line(raw, line_no)
            if translator.indent != 0:
                raise OmatError(f"unterminated block in function '{func.name}'")
            self.needs_linstep = self.needs_linstep or translator.needs_linstep
            self.needs_la_mod = self.needs_la_mod or translator.needs_la_mod
            self.la_names.update(translator.la_names)
            self.needs_random_mod = self.needs_random_mod or translator.needs_random_mod
            self.random_names.update(translator.random_names)
            self.random_specific_names.update(translator.random_specific_names)
            self.integer_env_kinds.update(translator.integer_env_kinds)
            if out:
                out.append("")
            out.extend(local_function_fortran(func, translator, arg_kinds, result_kind))
            emitted.add(name)
        return out

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


def has_omat_const_directive(line: str) -> bool:
    comment = matlab_comment_text(line)
    return comment is not None and re.search(r"\bomat\s*:\s*const\b", comment, re.IGNORECASE) is not None


def matlab_comment_text(line: str) -> str | None:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "%" and not in_single and not in_double:
            return line[i + 1 :]
    return None


def matlab_string_literal_value(text: str) -> str | None:
    stripped = text.strip()
    if len(stripped) < 2:
        return None
    quote = stripped[0]
    if quote not in {"'", '"'} or stripped[-1] != quote:
        return None
    body = stripped[1:-1]
    if quote == "'":
        return body.replace("''", "'")
    return bytes(body, "utf-8").decode("unicode_escape")


def fortran_string_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def join_multiline_statements(source: str) -> str:
    joined: list[str] = []
    buffer: list[str] = []
    start_line = 0
    depth = 0
    for line_no, raw in enumerate(source.splitlines(), start=1):
        text = raw.lstrip("\ufeff") if line_no == 1 else raw
        if not buffer:
            start_line = line_no
        buffer.append(text)
        clean = strip_comment(text)
        depth += bracket_delta_outside_strings(clean)
        continued = clean.rstrip().endswith("...")
        if depth <= 0 and not continued:
            joined.append(join_statement_lines(buffer, start_line))
            buffer = []
            depth = 0
    if buffer:
        raise OmatError(f"line {start_line}: unterminated bracketed expression")
    return "\n".join(joined)


def bracket_delta_outside_strings(text: str) -> int:
    in_single = False
    in_double = False
    delta = 0
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "[":
                delta += 1
            elif ch == "]":
                delta -= 1
    return delta


def join_statement_lines(lines: list[str], start_line: int) -> str:
    if len(lines) == 1:
        return lines[0]
    indent = re.match(r"\s*", lines[0]).group(0)
    parts: list[str] = []
    for i, line in enumerate(lines):
        text = strip_comment(line).strip()
        if i < len(lines) - 1:
            text = text.rstrip()
            if text.endswith("..."):
                text = text[:-3].rstrip()
            if text.endswith(";") or text.endswith(",") or text.endswith("["):
                parts.append(text)
            else:
                parts.append(text + ";")
        else:
            parts.append(text)
    return indent + " ".join(part for part in parts if part)


def matlab_fprintf_format(fmt: str) -> tuple[list[str], list[str | None], int, bool]:
    newline = fmt.endswith("\n")
    if newline:
        fmt = fmt[:-1]
    descriptors: list[str] = []
    format_args: list[str | None] = []
    literal: list[str] = []
    conversions = 0

    def flush_literal() -> None:
        nonlocal literal
        if literal:
            descriptors.append("a")
            format_args.append(fortran_string_literal("".join(literal)))
            literal = []

    i = 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == "\n":
            flush_literal()
            descriptors.append("/")
            format_args.append("__format_only__")
            i += 1
            continue
        if ch != "%":
            literal.append(ch)
            i += 1
            continue
        if i + 1 < len(fmt) and fmt[i + 1] == "%":
            literal.append("%")
            i += 2
            continue
        flush_literal()
        match = re.match(r"%([-+0 #]*)(\d*)(?:\.(\d+))?([fFeEgGdiIs])", fmt[i:])
        if match is None:
            raise OmatError(f"unsupported fprintf format near '{fmt[i:]}'")
        width = match.group(2) or "0"
        precision = match.group(3)
        code = match.group(4).lower()
        if code == "f":
            descriptors.append(f"__fixed_{width}_{precision or '8'}")
        elif code == "e":
            descriptors.append(f"__exp_{width}_{precision or '6'}")
        elif code == "g":
            descriptors.append(f"g{width}.{precision or '6'}")
        elif code in {"d", "i"}:
            descriptors.append(f"i{width}")
        elif code == "s":
            descriptors.append("a")
        format_args.append(None)
        conversions += 1
        i += len(match.group(0))
    flush_literal()
    if not descriptors:
        descriptors.append("a")
        format_args.append("''")
    return descriptors, format_args, conversions, newline


FUNCTION_RE = re.compile(
    r"^function\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$",
    re.IGNORECASE,
)


def is_known_function_name(name: str) -> bool:
    return (
        name in BUILTINS
        or name in LA_FUNCTIONS
        or name in RANDOM_DIST_PARAM_COUNTS
        or name in MATLAB_BUILTINS_NOT_IMPLEMENTED
        or name in STAT_SCALAR_FUNCTIONS
        or name in STAT_VECTOR_FUNCTIONS
        or name in STAT_MATRIX_FUNCTIONS
    )


def find_function_file(directory: Path, name: str) -> Path | None:
    candidate = directory / f"{name}.m"
    if candidate.exists():
        return candidate
    try:
        for path in directory.glob("*.m"):
            if path.stem.lower() == name:
                return path
    except OSError:
        return None
    return None


def read_function_file(path: Path) -> LocalFunction:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise OmatError(f"could not read function file '{path}': {exc}") from exc
    main_lines, functions = split_local_functions(source)
    extra = [
        raw
        for _, raw in main_lines
        if strip_comment(raw).strip()
    ]
    if extra:
        raise OmatError(f"function file '{path}' contains script statements before a function")
    if len(functions) != 1:
        raise OmatError(f"function file '{path}' must define exactly one function")
    return functions[0]


def split_local_functions(source: str) -> tuple[list[tuple[int, str]], list[LocalFunction]]:
    main_lines: list[tuple[int, str]] = []
    functions: list[LocalFunction] = []
    lines = list(enumerate(source.splitlines(), start=1))
    i = 0
    while i < len(lines):
        line_no, raw = lines[i]
        stripped = strip_comment(raw).strip().lstrip("\ufeff")
        match = FUNCTION_RE.match(stripped)
        if match is None:
            main_lines.append((line_no, raw.lstrip("\ufeff") if line_no == 1 else raw))
            i += 1
            continue
        result, name, arg_text = match.groups()
        args = [arg.strip() for arg in split_args(arg_text) if arg.strip()]
        body: list[tuple[int, str]] = []
        depth = 0
        i += 1
        while i < len(lines):
            body_line_no, body_raw = lines[i]
            body_stripped = strip_comment(body_raw).strip()
            low = body_stripped.lower()
            if low in {"end", "endfunction"} and depth == 0:
                break
            if low in {"end", "endfunction"}:
                depth = max(0, depth - 1)
            elif FOR_RE.match(body_stripped) is not None or IF_RE.match(body_stripped) is not None:
                depth += 1
            body.append((body_line_no, body_raw))
            i += 1
        if i >= len(lines):
            raise OmatError(f"function '{name}' is missing END")
        functions.append(LocalFunction(name=name, result=result, args=args, body=body))
        i += 1
    return main_lines, functions


def fortran_decl(kind: str, name: str, *, intent: str | None = None) -> str:
    attr = f", intent({intent})" if intent is not None else ""
    if kind == "integer":
        return f"integer{attr} :: {name}"
    if is_typed_integer_kind(kind):
        return f"integer({typed_integer_env_kind(kind)}){attr} :: {name}"
    if kind == "logical":
        return f"logical{attr} :: {name}"
    if kind == "string":
        return f"character(len=256){attr} :: {name}"
    if kind == "string_vector":
        return f"character(len=256){attr} :: {name}(:)"
    if kind == "integer_vector":
        return f"integer{attr} :: {name}(:)"
    if is_typed_integer_vector_kind(kind):
        return f"integer({typed_integer_env_kind(kind)}){attr} :: {name}(:)"
    if kind == "logical_vector":
        return f"logical{attr} :: {name}(:)"
    if kind == "logical_matrix":
        return f"logical{attr} :: {name}(:,:)"
    if kind == "real_vector":
        return f"real(real64){attr} :: {name}(:)"
    if kind == "real_matrix":
        return f"real(real64){attr} :: {name}(:,:)"
    return f"real(real64){attr} :: {name}"


def fortran_result_decl(kind: str, name: str) -> str:
    if kind.endswith("_vector"):
        if is_typed_integer_vector_kind(kind):
            base = f"integer({typed_integer_env_kind(kind)})"
        else:
            base = "integer" if kind == "integer_vector" else "logical" if kind == "logical_vector" else "real(real64)"
        return f"{base}, allocatable :: {name}(:)"
    if kind.endswith("_matrix"):
        base = "logical" if kind == "logical_matrix" else "real(real64)"
        return f"{base}, allocatable :: {name}(:,:)"
    return fortran_decl(kind, name)


def parameter_declaration(sym: Symbol) -> str:
    if sym.value is None:
        raise OmatError(f"constant '{sym.name}' has no value")
    if sym.kind == "integer":
        return f"integer, parameter :: {sym.name} = {sym.value}"
    if is_typed_integer_kind(sym.kind):
        return f"integer({typed_integer_env_kind(sym.kind)}), parameter :: {sym.name} = {sym.value}"
    if sym.kind == "logical":
        return f"logical, parameter :: {sym.name} = {sym.value}"
    if sym.kind == "real":
        return f"real(real64), parameter :: {sym.name} = {sym.value}"
    raise OmatError("% omat: const currently supports scalar constants only")


def local_function_fortran(
    func: LocalFunction,
    translator: Translator,
    arg_kinds: list[str],
    result_kind: str,
) -> list[str]:
    lines = [f"function {func.name}({', '.join(func.args)}) result({func.result})"]
    for arg, kind in zip(func.args, arg_kinds):
        lines.append(fortran_decl(kind, arg, intent="in"))
    lines.append(fortran_result_decl(result_kind, func.result))
    for sym in translator.symbols.values():
        if sym.name.lower() in {func.result.lower(), *(arg.lower() for arg in func.args)}:
            continue
        lines.append(fortran_result_decl(sym.kind, sym.name))
    if translator.symbols:
        lines.append("")
    for stmt in translator.statements:
        lines.append("  " * stmt.indent + stmt.text)
    lines.append(f"end function {func.name}")
    return lines


DECL_RE = re.compile(
    r"^(\s*(?:integer(?:\([^)]*\))?|logical(?:\([^)]*\))?|real(?:\([^)]*\))?|character(?:\([^)]*\))?)"
    r"(?:\s*,\s*[^:]*)?)\s*::\s*(\S.*)$",
    re.IGNORECASE,
)


def coalesce_fortran_declarations(lines: list[str]) -> list[str]:
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        out.extend(coalesced_declaration_run(run))
        run.clear()

    for line in lines:
        if declaration_parts(line) is None:
            flush()
            out.append(line)
        else:
            run.append(line)
    flush()
    return out


def coalesced_declaration_run(lines: list[str]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    prefixes: list[str] = []
    for line in lines:
        parts = declaration_parts(line)
        if parts is None:
            continue
        prefix, names = parts
        if prefix not in grouped:
            prefixes.append(prefix)
            grouped[prefix] = []
        grouped[prefix].extend(names)
    return [f"{prefix} :: {', '.join(grouped[prefix])}" for prefix in prefixes]


def declaration_parts(line: str) -> tuple[str, list[str]] | None:
    if "!" in line:
        return None
    match = DECL_RE.match(line)
    if match is None:
        return None
    names = [name.strip() for name in split_args(match.group(2)) if name.strip()]
    if not names:
        return None
    return match.group(1).rstrip(), names


def wrap_fortran_source(source: str, limit: int = 80) -> str:
    return "\n".join(wrap_fortran_line(line, limit) for line in source.splitlines())


def wrap_fortran_line(line: str, limit: int = 80) -> str:
    if len(line) <= limit or line.lstrip().startswith("!"):
        return line

    out: list[str] = []
    current = line
    base_indent = re.match(r"^\s*", line).group(0)
    continuation_prefix = base_indent + "  & "
    while len(current) > limit:
        break_pos = find_fortran_wrap_position(current, limit - 2)
        if break_pos <= 0:
            break
        out.append(current[: break_pos + 1].rstrip() + " &")
        current = continuation_prefix + current[break_pos + 1 :].lstrip()
    out.append(current)
    return "\n".join(out)


def find_fortran_wrap_position(line: str, max_pos: int) -> int:
    in_single = False
    in_double = False
    candidates: list[int] = []
    for i, ch in enumerate(line):
        if i > max_pos:
            break
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and ch in {",", " ", "+", "-", "*", "/"}:
            candidates.append(i)
    if not candidates:
        return -1
    for ch in (",", " ", "+", "-", "*", "/"):
        for pos in reversed(candidates):
            if line[pos] == ch:
                return pos
    return candidates[-1]


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


def parse_index_expr(text: str) -> tuple[str, list[str]] | None:
    stripped = text.strip()
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", stripped)
    if not m:
        return None
    name = m.group(1)
    if name.lower() in BUILTINS or name.lower() in LA_FUNCTIONS or name.lower() in RANDOM_DIST_PARAM_COUNTS:
        return None
    return name, split_args(m.group(2))


def index_selects_many(index: str) -> bool:
    text = index.strip()
    return (
        text == ":"
        or len(split_top_level_colon(text)) in {2, 3}
        or (text.startswith("[") and text.endswith("]"))
    )


def vector_element_kind(kind: str) -> str:
    if kind == "integer_vector":
        return "integer"
    if is_typed_integer_vector_kind(kind):
        return typed_integer_scalar_kind(kind)
    if kind == "logical_vector":
        return "logical"
    if kind == "string_vector":
        return "string"
    return "real"


def is_typed_integer_kind(kind: str) -> bool:
    return re.fullmatch(r"integer_int(?:8|16|32|64)", kind) is not None


def is_typed_integer_vector_kind(kind: str) -> bool:
    return re.fullmatch(r"integer_int(?:8|16|32|64)_vector", kind) is not None


def typed_integer_scalar_kind(kind: str) -> str:
    if is_typed_integer_vector_kind(kind):
        return kind.removesuffix("_vector")
    return kind


def typed_integer_env_kind(kind: str) -> str:
    scalar = typed_integer_scalar_kind(kind)
    return scalar.removeprefix("integer_")


def is_vector_expr(text: str) -> bool:
    if is_flatten_expr(text):
        return True
    if len(split_top_level_colon(text.strip())) in {2, 3}:
        return True
    m = MATRIX_FUNC_RE.match(text)
    if m is not None:
        args = split_args(m.group(2))
        return len(args) == 1 or (len(args) == 2 and args[1].strip() == "1")
    return (
        (text.startswith("[") and ";" not in text)
        or re.match(r"^linspace\s*\(", text, re.IGNORECASE) is not None
        or re.match(r"^logspace\s*\(", text, re.IGNORECASE) is not None
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


def contains_vector_randi_call(text: str) -> bool:
    for match in re.finditer(r"\brandi\s*\(([^()]*)\)", text, re.IGNORECASE):
        args = split_args(match.group(1))
        if len(args) >= 2:
            return True
    return False


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
            return sym is not None and (sym.kind == "integer" or is_typed_integer_kind(sym.kind))
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


def is_integer_declaration_expr(text: str, symbols: dict[str, Symbol]) -> bool:
    stripped = text.strip()
    if is_integer_numeric_literal(stripped):
        return False
    if not is_integer_expr(stripped, symbols):
        return False
    return any(op in stripped for op in ("^", "*", "+", "-", "%")) or bool(IDENT_RE.search(stripped))


def is_typed_integer_expr(text: str, symbols: dict[str, Symbol]) -> bool:
    source = text.strip().replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return False
    saw_typed = False

    def visit(node: ast.AST) -> bool:
        nonlocal saw_typed
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return isinstance(node.value, int) and not isinstance(node.value, bool)
        if isinstance(node, ast.Name):
            sym = symbols.get(node.id.lower())
            if sym is None:
                return False
            if is_typed_integer_kind(sym.kind):
                saw_typed = True
                return True
            return sym.kind == "integer"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                return False
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Pow)):
                return False
            return visit(node.left) and visit(node.right)
        return False

    return visit(tree) and saw_typed


def identifier_is_indexed(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\s*\(", text) is not None


def identifier_only_occurs_as_argument_to_scalar_function(text: str, name: str) -> bool:
    occurrences = list(re.finditer(rf"\b{re.escape(name)}\b", text))
    if not occurrences:
        return False
    scalar_arg_spans: list[tuple[int, int]] = []
    for func in STAT_SCALAR_FUNCTIONS | LA_SCALAR_FUNCTIONS:
        for match in re.finditer(rf"\b{re.escape(func)}\s*\(([^()]*)\)", text, re.IGNORECASE):
            scalar_arg_spans.append((match.start(1), match.end(1)))
    if not scalar_arg_spans:
        return False
    return all(
        any(start <= match.start() and match.end() <= end for start, end in scalar_arg_spans)
        for match in occurrences
    )


def clean_emitted_helper_names(source: str) -> str:
    lines: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip().lower()
        if stripped.startswith("public ::"):
            line = line.replace("disp_omat", "print_vector")
        elif stripped.startswith("use m_mod, only:"):
            line = line.replace("disp_omat", "disp => print_vector")
        else:
            line = re.sub(r"\bcall\s+disp_omat\s*\(", "call disp(", line)
        lines.append(line)
    source = "\n".join(lines)
    return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)_omat([0-9]*)\b", r"\1\2", source)


def convert_elementwise(text: str) -> str:
    out = (
        text.replace(".^", "**")
        .replace(".*", "*")
        .replace("./", "/")
        .replace("~=", "/=")
        .replace("&&", ".and.")
        .replace("||", ".or.")
    )
    return re.sub(r"~\s*", ".not. ", out)


def convert_logical_literals(text: str) -> str:
    text = re.sub(r"(?<!\.)\btrue\b(?!\.)", ".true.", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\.)\bfalse\b(?!\.)", ".false.", text, flags=re.IGNORECASE)
    return text


def convert_pi_constant(text: str) -> str:
    return re.sub(r"\bpi\b", "acos(-1.0_real64)", text, flags=re.IGNORECASE)


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
            items = coerce_real_literal_items(split_matlab_literal_row(body))
            return "[" + ", ".join(items) + "]"
        rows = []
        ncols = None
        for raw_row in body.split(";"):
            row = coerce_real_literal_items(split_matlab_literal_row(raw_row.strip()))
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


def coerce_real_literal_items(items: list[str]) -> list[str]:
    if not any(is_real_numeric_literal(item) for item in items):
        return items
    return [f"{item}.0" if is_integer_numeric_literal(item) else item for item in items]


def typed_integer_vector_literal(text: str, kind_name: str) -> str | None:
    stripped = text.strip()
    if not (stripped.startswith("[") and stripped.endswith("]") and ";" not in stripped):
        return None
    items = split_matlab_literal_row(stripped[1:-1].strip())
    if not items or not all(integer_literal_text(item) is not None for item in items):
        return None
    return "[" + ", ".join(f"{integer_literal_text(item)}_{kind_name}" for item in items) + "]"


def integer_literal_text(text: str) -> str | None:
    stripped = text.strip()
    if is_integer_numeric_literal(stripped):
        return stripped
    return None


def is_integer_numeric_literal(text: str) -> bool:
    return re.fullmatch(r"[+-]?\d+", text.strip()) is not None


def is_real_numeric_literal(text: str) -> bool:
    return re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+(?:[eEdD][+-]?\d+))", text.strip()) is not None


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
    in_single = False
    in_double = False
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and ch in "([":
            depth += 1
        elif not in_single and not in_double and ch in ")]":
            depth -= 1
        if ch == "," and depth == 0 and not in_single and not in_double:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def split_top_level_colon(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch == ":":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if not parts:
        return []
    parts.append("".join(current).strip())
    if len(parts) not in {2, 3} or any(not part for part in parts):
        return []
    return parts


def split_top_level_backslash(text: str) -> tuple[str, str] | None:
    in_single = False
    in_double = False
    depth = 0
    for i, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "\\" and depth == 0:
                left = text[:i].strip()
                right = text[i + 1 :].strip()
                if left and right:
                    return left, right
    return None


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
    m = CONST_ASSIGN_RE.match(stripped)
    if m is None:
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
    m_interface = re.match(r"^interface\s+([A-Za-z_][A-Za-z0-9_]*)\b", block[0])
    if m_interface is not None:
        return m_interface.group(1)
    m = re.match(r"^(?:[A-Za-z0-9_(), ]+\s+)?(?:function|subroutine)\s+([A-Za-z_][A-Za-z0-9_]*)\b", block[0])
    return None if m is None else m.group(1)


def helper_references(text: str, helper_names: set[str]) -> set[str]:
    refs: set[str] = set()
    for name in helper_names:
        if re.search(rf"\b{re.escape(name)}\s*\(", text):
            refs.add(name)
    if re.search(r"\bdisp_omat\s*\(", text):
        refs.add("disp_omat")
        if {
            "print_real_vector_omat",
            "print_integer_vector_omat",
            "print_logical_vector_omat",
        } <= helper_names:
            refs.update({"print_real_vector_omat", "print_integer_vector_omat", "print_logical_vector_omat"})
    if re.search(r"\bprint_vector_omat\s*\(", text) and {
        "print_real_vector_omat",
        "print_integer_vector_omat",
        "print_logical_vector_omat",
    } <= helper_names:
        refs.update({"print_real_vector_omat", "print_integer_vector_omat", "print_logical_vector_omat"})
    return refs


def direct_helper_names(body_lines: list[str], helper_names: list[str]) -> list[str]:
    refs = helper_references("\n".join(body_lines), set(helper_names))
    return [name for name in helper_names if name in refs]


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


def helper_source(
    include_linspace: bool,
    body_lines: list[str] | None = None,
    *,
    use_generic_print: bool = False,
) -> list[str]:
    real_vector_printer = "print_vector_omat" if use_generic_print else "print_real_vector_omat"
    logical_vector_printer = "print_vector_omat" if use_generic_print else "print_logical_vector_omat"
    lines = [
        "logical function exist_file_omat(path)",
        "character(len=*), intent(in) :: path",
        "inquire(file=trim(path), exist=exist_file_omat)",
        "end function exist_file_omat",
        "",
        "subroutine read_textscan_string_real_omat(unit, labels, values)",
        "integer, intent(in) :: unit",
        "character(len=256), allocatable, intent(out) :: labels(:)",
        "real(real64), allocatable, intent(out) :: values(:)",
        "character(len=256), allocatable :: tmp_labels(:)",
        "real(real64), allocatable :: tmp_values(:)",
        "integer :: ios, n, capacity",
        "capacity = 1024",
        "n = 0",
        "allocate(tmp_labels(capacity), tmp_values(capacity))",
        "do",
        "  if (n == capacity) call grow_textscan_string_real_omat(tmp_labels, tmp_values, capacity)",
        "  read(unit, *, iostat=ios) tmp_labels(n + 1), tmp_values(n + 1)",
        "  if (ios /= 0) exit",
        "  n = n + 1",
        "end do",
        "allocate(labels(n), values(n))",
        "if (n > 0) then",
        "  labels = tmp_labels(1:n)",
        "  values = tmp_values(1:n)",
        "end if",
        "end subroutine read_textscan_string_real_omat",
        "",
        "subroutine grow_textscan_string_real_omat(labels, values, capacity)",
        "character(len=256), allocatable, intent(inout) :: labels(:)",
        "real(real64), allocatable, intent(inout) :: values(:)",
        "integer, intent(inout) :: capacity",
        "character(len=256), allocatable :: new_labels(:)",
        "real(real64), allocatable :: new_values(:)",
        "integer :: old_capacity",
        "old_capacity = capacity",
        "capacity = max(1, 2 * capacity)",
        "allocate(new_labels(capacity), new_values(capacity))",
        "new_labels(1:old_capacity) = labels",
        "new_values(1:old_capacity) = values",
        "call move_alloc(new_labels, labels)",
        "call move_alloc(new_values, values)",
        "end subroutine grow_textscan_string_real_omat",
        "",
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
        "integer function randi_scalar_omat(imin, imax) result(x)",
        "integer, intent(in) :: imin, imax",
        "real(real64) :: u",
        "call random_number(u)",
        "x = imin + int(u * real(imax - imin + 1, real64))",
        "if (x > imax) x = imax",
        "end function randi_scalar_omat",
        "",
        "function randi_vec_omat(imin, imax, n) result(x)",
        "integer, intent(in) :: imin, imax, n",
        "integer, allocatable :: x(:)",
        "real(real64), allocatable :: u(:)",
        "allocate(x(n), u(n))",
        "call random_number(u)",
        "x = imin + int(u * real(imax - imin + 1, real64))",
        "where (x > imax) x = imax",
        "end function randi_vec_omat",
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
        "function eye_omat(nrow, ncol) result(x)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: x(:,:)",
        "integer :: i, n",
        "n = min(nrow, ncol)",
        "allocate(x(nrow, ncol))",
        "x = 0.0_real64",
        "do i = 1, n",
        "  x(i, i) = 1.0_real64",
        "end do",
        "end function eye_omat",
        "",
        "function diag_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i",
        "allocate(y(size(x), size(x)))",
        "y = 0.0_real64",
        "do i = 1, size(x)",
        "  y(i, i) = x(i)",
        "end do",
        "end function diag_vec_omat",
        "",
        "function diag_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i, n",
        "n = min(size(x, 1), size(x, 2))",
        "allocate(y(n))",
        "do i = 1, n",
        "  y(i) = x(i, i)",
        "end do",
        "end function diag_mat_omat",
        "",
        "function repmat_vec_omat(x, nrow, ncol) result(y)",
        "real(real64), intent(in) :: x(:)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i, j",
        "allocate(y(nrow, size(x) * ncol))",
        "do i = 1, nrow",
        "  do j = 1, ncol",
        "    y(i, (j - 1) * size(x) + 1:j * size(x)) = x",
        "  end do",
        "end do",
        "end function repmat_vec_omat",
        "",
        "function repmat_mat_omat(x, nrow, ncol) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "integer, intent(in) :: nrow, ncol",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i, j, nr, nc",
        "nr = size(x, 1)",
        "nc = size(x, 2)",
        "allocate(y(nr * nrow, nc * ncol))",
        "do i = 1, nrow",
        "  do j = 1, ncol",
        "    y((i - 1) * nr + 1:i * nr, (j - 1) * nc + 1:j * nc) = x",
        "  end do",
        "end do",
        "end function repmat_mat_omat",
        "",
        "function hcat_mats_omat(a, b) result(c)",
        "real(real64), intent(in) :: a(:,:), b(:,:)",
        "real(real64), allocatable :: c(:,:)",
        "integer :: nca, ncb",
        "if (size(a, 1) /= size(b, 1)) then",
        "  print *, 'omat horizontal concatenation row mismatch'",
        "  stop 1",
        "end if",
        "nca = size(a, 2)",
        "ncb = size(b, 2)",
        "allocate(c(size(a, 1), nca + ncb))",
        "c(:, 1:nca) = a",
        "c(:, nca + 1:nca + ncb) = b",
        "end function hcat_mats_omat",
        "",
        "function eigvals_omat(a) result(vals)",
        "real(real64), intent(in) :: a(:,:)",
        "real(real64), allocatable :: vals(:)",
        "real(real64), allocatable :: vecs(:,:)",
        "call jacobi_symmetric_omat(a, vals, vecs)",
        "end function eigvals_omat",
        "",
        "function eigvecs_omat(a) result(vecs)",
        "real(real64), intent(in) :: a(:,:)",
        "real(real64), allocatable :: vecs(:,:)",
        "real(real64), allocatable :: vals(:)",
        "call jacobi_symmetric_omat(a, vals, vecs)",
        "end function eigvecs_omat",
        "",
        "subroutine jacobi_symmetric_omat(a, vals, vecs)",
        "real(real64), intent(in) :: a(:,:)",
        "real(real64), allocatable, intent(out) :: vals(:), vecs(:,:)",
        "real(real64), allocatable :: work(:,:)",
        "real(real64) :: app, aqq, apq, tau, t, c, s, max_off",
        "real(real64) :: akp, akq, vkp, vkq, tmp",
        "integer :: n, i, j, k, p, q, iter, max_iter, best",
        "n = size(a, 1)",
        "if (size(a, 2) /= n) then",
        "  print *, 'omat eig requires a square matrix'",
        "  stop 1",
        "end if",
        "if (n <= 0) then",
        "  print *, 'omat eig requires a nonempty matrix'",
        "  stop 1",
        "end if",
        "if (maxval(abs(a - transpose(a))) > 1.0e-10_real64) then",
        "  print *, 'omat eig currently supports real symmetric matrices'",
        "  stop 1",
        "end if",
        "allocate(work(n, n), vals(n), vecs(n, n))",
        "work = a",
        "vecs = 0.0_real64",
        "do i = 1, n",
        "  vecs(i, i) = 1.0_real64",
        "end do",
        "max_iter = max(1, 100 * n * n)",
        "do iter = 1, max_iter",
        "  p = 1",
        "  q = min(2, n)",
        "  max_off = 0.0_real64",
        "  do j = 2, n",
        "    do i = 1, j - 1",
        "      if (abs(work(i, j)) > max_off) then",
        "        max_off = abs(work(i, j))",
        "        p = i",
        "        q = j",
        "      end if",
        "    end do",
        "  end do",
        "  if (max_off < 1.0e-12_real64) exit",
        "  app = work(p, p)",
        "  aqq = work(q, q)",
        "  apq = work(p, q)",
        "  tau = (aqq - app) / (2.0_real64 * apq)",
        "  t = sign(1.0_real64, tau) / (abs(tau) + sqrt(1.0_real64 + tau*tau))",
        "  c = 1.0_real64 / sqrt(1.0_real64 + t*t)",
        "  s = t * c",
        "  work(p, p) = app - t * apq",
        "  work(q, q) = aqq + t * apq",
        "  work(p, q) = 0.0_real64",
        "  work(q, p) = 0.0_real64",
        "  do k = 1, n",
        "    if (k /= p .and. k /= q) then",
        "      akp = work(k, p)",
        "      akq = work(k, q)",
        "      work(k, p) = c * akp - s * akq",
        "      work(p, k) = work(k, p)",
        "      work(k, q) = s * akp + c * akq",
        "      work(q, k) = work(k, q)",
        "    end if",
        "  end do",
        "  do k = 1, n",
        "    vkp = vecs(k, p)",
        "    vkq = vecs(k, q)",
        "    vecs(k, p) = c * vkp - s * vkq",
        "    vecs(k, q) = s * vkp + c * vkq",
        "  end do",
        "end do",
        "do i = 1, n",
        "  vals(i) = work(i, i)",
        "end do",
        "do i = 1, n - 1",
        "  best = i",
        "  do j = i + 1, n",
        "    if (vals(j) < vals(best)) best = j",
        "  end do",
        "  if (best /= i) then",
        "    tmp = vals(i)",
        "    vals(i) = vals(best)",
        "    vals(best) = tmp",
        "    do k = 1, n",
        "      tmp = vecs(k, i)",
        "      vecs(k, i) = vecs(k, best)",
        "      vecs(k, best) = tmp",
        "    end do",
        "  end if",
        "end do",
        "do j = 1, n",
        "  do i = n, 1, -1",
        "    if (abs(vecs(i, j)) > 1.0e-12_real64) then",
        "      if (vecs(i, j) < 0.0_real64) vecs(:, j) = -vecs(:, j)",
        "      exit",
        "    end if",
        "  end do",
        "end do",
        "end subroutine jacobi_symmetric_omat",
        "",
        "function mldivide_omat(a, b) result(x)",
        "real(real64), intent(in) :: a(:,:), b(:)",
        "real(real64), allocatable :: x(:)",
        "if (size(a, 1) == size(a, 2)) then",
        "  x = solve_linear_omat(a, b)",
        "else",
        "  x = solve_linear_omat(matmul(transpose(a), a), matmul(transpose(a), b))",
        "end if",
        "end function mldivide_omat",
        "",
        "function solve_linear_omat(a, b) result(x)",
        "real(real64), intent(in) :: a(:,:), b(:)",
        "real(real64), allocatable :: x(:)",
        "real(real64), allocatable :: aa(:,:), bb(:)",
        "real(real64) :: factor, pivot_value, temp",
        "integer :: n, i, j, k, pivot",
        "n = size(a, 1)",
        "if (size(a, 2) /= n .or. size(b) /= n) then",
        "  print *, 'omat linear solve shape mismatch'",
        "  stop 1",
        "end if",
        "allocate(aa(n, n), bb(n), x(n))",
        "aa = a",
        "bb = b",
        "do k = 1, n - 1",
        "  pivot = k",
        "  pivot_value = abs(aa(k, k))",
        "  do i = k + 1, n",
        "    if (abs(aa(i, k)) > pivot_value) then",
        "      pivot = i",
        "      pivot_value = abs(aa(i, k))",
        "    end if",
        "  end do",
        "  if (pivot_value == 0.0_real64) then",
        "    print *, 'omat singular matrix in left divide'",
        "    stop 1",
        "  end if",
        "  if (pivot /= k) then",
        "    do j = k, n",
        "      temp = aa(k, j)",
        "      aa(k, j) = aa(pivot, j)",
        "      aa(pivot, j) = temp",
        "    end do",
        "    temp = bb(k)",
        "    bb(k) = bb(pivot)",
        "    bb(pivot) = temp",
        "  end if",
        "  do i = k + 1, n",
        "    factor = aa(i, k) / aa(k, k)",
        "    aa(i, k:n) = aa(i, k:n) - factor * aa(k, k:n)",
        "    bb(i) = bb(i) - factor * bb(k)",
        "  end do",
        "end do",
        "if (aa(n, n) == 0.0_real64) then",
        "  print *, 'omat singular matrix in left divide'",
        "  stop 1",
        "end if",
        "do i = n, 1, -1",
        "  if (i < n) then",
        "    x(i) = (bb(i) - sum(aa(i, i + 1:n) * x(i + 1:n))) / aa(i, i)",
        "  else",
        "    x(i) = bb(i) / aa(i, i)",
        "  end if",
        "end do",
        "end function solve_linear_omat",
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
        "subroutine print_real_scalar_omat(x)",
        "real(real64), intent(in) :: x",
        "write(*,'(a)') trim(real_text_omat(x))",
        "end subroutine print_real_scalar_omat",
        "",
        "function real_text_omat(x) result(text)",
        "real(real64), intent(in) :: x",
        "character(len=32) :: text",
        "integer :: last",
        "if (x /= x) then",
        "  text = 'NaN'",
        "  return",
        "end if",
        "if (x == 0.0_real64) then",
        "  text = '0'",
        "  return",
        "end if",
        "if (x /= 0.0_real64 .and. (abs(x) < 1.0e-4_real64 .or. abs(x) >= 1.0e7_real64)) then",
        "  write(text,'(es14.6)') x",
        "else",
        "  write(text,'(f0.8)') x",
        "  text = adjustl(text)",
        "  if (text(1:1) == '.') text = '0' // trim(text)",
        "  if (text(1:2) == '-.') text = '-0' // trim(text(2:))",
        "  last = len_trim(text)",
        "  do while (last > 1 .and. text(last:last) == '0')",
        "    text(last:last) = ' '",
        "    last = last - 1",
        "  end do",
        "  if (last > 1 .and. text(last:last) == '.') text(last:last) = ' '",
        "end if",
        "end function real_text_omat",
        "",
        "function fixed_text_omat(x, ndigits) result(text)",
        "real(real64), intent(in) :: x",
        "integer, intent(in) :: ndigits",
        "character(len=64) :: text",
        "character(len=16) :: fmt",
        "write(fmt,'(\"(f0.\",i0,\")\")') ndigits",
        "write(text,fmt) x",
        "text = adjustl(text)",
        "if (text(1:1) == '.') text = '0' // trim(text)",
        "if (text(1:2) == '-.') text = '-0' // trim(text(2:))",
        "end function fixed_text_omat",
        "",
        "function exp_text_omat(x, ndigits) result(text)",
        "real(real64), intent(in) :: x",
        "integer, intent(in) :: ndigits",
        "character(len=64) :: text",
        "character(len=16) :: fmt",
        "integer :: i",
        "write(fmt,'(\"(es0.\",i0,\"e2)\")') ndigits",
        "write(text,fmt) x",
        "text = adjustl(text)",
        "do i = 1, len_trim(text)",
        "  if (text(i:i) == 'E') text(i:i) = 'e'",
        "end do",
        "end function exp_text_omat",
        "",
        "subroutine print_integer_scalar_omat(x)",
        "integer, intent(in) :: x",
        "write(*,'(i0)') x",
        "end subroutine print_integer_scalar_omat",
        "",
        "subroutine print_logical_scalar_omat(x)",
        "logical, intent(in) :: x",
        "write(*,'(l1)') x",
        "end subroutine print_logical_scalar_omat",
        "",
        "subroutine print_real_vector_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "integer :: i",
        "do i = 1, size(x)",
        "  if (i > 1) write(*,'(1x)', advance='no')",
        "  write(*,'(a)', advance='no') trim(real_text_omat(x(i)))",
        "end do",
        "write(*,*)",
        "end subroutine print_real_vector_omat",
        "",
        "subroutine print_integer_vector_omat(x)",
        "integer, intent(in) :: x(:)",
        "write(*,'(*(1x,i0))') x",
        "end subroutine print_integer_vector_omat",
        "",
        "subroutine print_logical_vector_omat(x)",
        "logical, intent(in) :: x(:)",
        "write(*,'(*(1x,l1))') x",
        "end subroutine print_logical_vector_omat",
        "",
        "subroutine print_real_matrix_omat(x)",
        "real(real64), intent(in) :: x(:,:)",
        "integer :: i",
        "do i = 1, size(x, 1)",
        f"  call {real_vector_printer}(x(i, :))",
        "end do",
        "end subroutine print_real_matrix_omat",
        "",
        "subroutine print_logical_matrix_omat(x)",
        "logical, intent(in) :: x(:,:)",
        "integer :: i",
        "do i = 1, size(x, 1)",
        f"  call {logical_vector_printer}(x(i, :))",
        "end do",
        "end subroutine print_logical_matrix_omat",
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
        "function mean_mat_dim2_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i",
        "allocate(y(size(x, 1)))",
        "do i = 1, size(x, 1)",
        "  y(i) = mean_vec_omat(x(i, :))",
        "end do",
        "end function mean_mat_dim2_omat",
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
        "function std_mat_dim2_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i",
        "allocate(y(size(x, 1)))",
        "do i = 1, size(x, 1)",
        "  y(i) = std_vec_omat(x(i, :))",
        "end do",
        "end function std_mat_dim2_omat",
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
        "real(real64) function trapz_omat(x, y)",
        "real(real64), intent(in) :: x(:), y(:)",
        "integer :: i",
        "if (size(x) /= size(y)) then",
        "  print *, 'omat trapz size mismatch'",
        "  stop 1",
        "end if",
        "trapz_omat = 0.0_real64",
        "do i = 1, size(x) - 1",
        "  trapz_omat = trapz_omat + 0.5_real64 * (x(i+1) - x(i)) * (y(i) + y(i+1))",
        "end do",
        "end function trapz_omat",
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
        "function cumtrapz_vec_omat(yin) result(yout)",
        "real(real64), intent(in) :: yin(:)",
        "real(real64), allocatable :: yout(:)",
        "integer :: i",
        "allocate(yout(size(yin)))",
        "if (size(yin) >= 1) yout(1) = 0.0_real64",
        "do i = 2, size(yin)",
        "  yout(i) = yout(i - 1) + 0.5_real64 * (yin(i - 1) + yin(i))",
        "end do",
        "end function cumtrapz_vec_omat",
        "",
        "function cumtrapz_xy_omat(x, yin) result(yout)",
        "real(real64), intent(in) :: x(:), yin(:)",
        "real(real64), allocatable :: yout(:)",
        "integer :: i",
        "if (size(x) /= size(yin)) then",
        "  print *, 'omat cumtrapz size mismatch'",
        "  stop 1",
        "end if",
        "allocate(yout(size(yin)))",
        "if (size(yin) >= 1) yout(1) = 0.0_real64",
        "do i = 2, size(yin)",
        "  yout(i) = yout(i - 1) + 0.5_real64 * (x(i) - x(i - 1)) * (yin(i - 1) + yin(i))",
        "end do",
        "end function cumtrapz_xy_omat",
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
        "function cumprod_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i",
        "allocate(y(size(x)))",
        "if (size(x) >= 1) y(1) = x(1)",
        "do i = 2, size(x)",
        "  y(i) = y(i - 1) * x(i)",
        "end do",
        "end function cumprod_vec_omat",
        "",
        "function cumprod_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i, j",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  if (size(x, 1) >= 1) y(1, j) = x(1, j)",
        "  do i = 2, size(x, 1)",
        "    y(i, j) = y(i - 1, j) * x(i, j)",
        "  end do",
        "end do",
        "end function cumprod_mat_omat",
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
        "function floor_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "allocate(y(size(x)))",
        "y = real(floor(x), real64)",
        "end function floor_vec_omat",
        "",
        "function floor_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "y = real(floor(x), real64)",
        "end function floor_mat_omat",
        "",
        "function ceil_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "allocate(y(size(x)))",
        "y = real(ceiling(x), real64)",
        "end function ceil_vec_omat",
        "",
        "function ceil_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "y = real(ceiling(x), real64)",
        "end function ceil_mat_omat",
        "",
        "function round_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "allocate(y(size(x)))",
        "y = anint(x)",
        "end function round_vec_omat",
        "",
        "function round_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "y = anint(x)",
        "end function round_mat_omat",
        "",
        "function fix_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "allocate(y(size(x)))",
        "y = aint(x)",
        "end function fix_vec_omat",
        "",
        "function fix_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "y = aint(x)",
        "end function fix_mat_omat",
        "",
        "function sign_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "allocate(y(size(x)))",
        "y = merge(1.0_real64, merge(-1.0_real64, 0.0_real64, x < 0.0_real64), x > 0.0_real64)",
        "end function sign_vec_omat",
        "",
        "function sign_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "y = merge(1.0_real64, merge(-1.0_real64, 0.0_real64, x < 0.0_real64), x > 0.0_real64)",
        "end function sign_mat_omat",
        "",
        "function flip_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "integer :: i, n",
        "n = size(x)",
        "allocate(y(n))",
        "do i = 1, n",
        "  y(i) = x(n + 1 - i)",
        "end do",
        "end function flip_vec_omat",
        "",
        "function flip_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: i, nrow",
        "nrow = size(x, 1)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do i = 1, nrow",
        "  y(i, :) = x(nrow + 1 - i, :)",
        "end do",
        "end function flip_mat_omat",
        "",
        "function flipud_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "y = flip_mat_omat(x)",
        "end function flipud_mat_omat",
        "",
        "function fliplr_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "integer :: j, ncol",
        "ncol = size(x, 2)",
        "allocate(y(size(x, 1), size(x, 2)))",
        "do j = 1, ncol",
        "  y(:, j) = x(:, ncol + 1 - j)",
        "end do",
        "end function fliplr_mat_omat",
        "",
        "function transpose_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x), 1))",
        "y(:, 1) = x",
        "end function transpose_vec_omat",
        "",
        "function transpose_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:,:)",
        "allocate(y(size(x, 2), size(x, 1)))",
        "y = transpose(x)",
        "end function transpose_mat_omat",
        "",
        "function vcat_vecs_omat(x, y) result(z)",
        "real(real64), intent(in) :: x(:), y(:)",
        "real(real64), allocatable :: z(:,:)",
        "if (size(x) /= size(y)) error stop 'vertical concatenation requires equal row lengths'",
        "allocate(z(2, size(x)))",
        "z(1, :) = x",
        "z(2, :) = y",
        "end function vcat_vecs_omat",
        "",
        "real(real64) function min_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "min_vec_omat = minval(x)",
        "end function min_vec_omat",
        "",
        "function min_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = minval(x(:, j))",
        "end do",
        "end function min_mat_omat",
        "",
        "real(real64) function max_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "max_vec_omat = maxval(x)",
        "end function max_vec_omat",
        "",
        "function max_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = maxval(x(:, j))",
        "end do",
        "end function max_mat_omat",
        "",
        "real(real64) function prod_vec_omat(x)",
        "real(real64), intent(in) :: x(:)",
        "prod_vec_omat = product(x)",
        "end function prod_vec_omat",
        "",
        "function prod_mat_omat(x) result(y)",
        "real(real64), intent(in) :: x(:,:)",
        "real(real64), allocatable :: y(:)",
        "integer :: j",
        "allocate(y(size(x, 2)))",
        "do j = 1, size(x, 2)",
        "  y(j) = product(x(:, j))",
        "end do",
        "end function prod_mat_omat",
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
        "function find_k_vec_omat(mask, k) result(idx)",
        "logical, intent(in) :: mask(:)",
        "integer, intent(in) :: k",
        "integer, allocatable :: idx(:)",
        "integer :: i, n, nkeep",
        "nkeep = min(max(0, k), count(mask))",
        "allocate(idx(nkeep))",
        "n = 0",
        "do i = 1, size(mask)",
        "  if (mask(i)) then",
        "    n = n + 1",
        "    if (n <= nkeep) idx(n) = i",
        "    if (n >= nkeep) exit",
        "  end if",
        "end do",
        "end function find_k_vec_omat",
        "",
        "function unique_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "real(real64), allocatable :: s(:)",
        "integer :: i, n",
        "s = sort_vec_omat(x)",
        "n = 0",
        "do i = 1, size(s)",
        "  if (i == 1 .or. s(i) /= s(i - 1)) n = n + 1",
        "end do",
        "allocate(y(n))",
        "n = 0",
        "do i = 1, size(s)",
        "  if (i == 1 .or. s(i) /= s(i - 1)) then",
        "    n = n + 1",
        "    y(n) = s(i)",
        "  end if",
        "end do",
        "end function unique_vec_omat",
        "",
        "function ismember_vec_omat(x, y) result(mask)",
        "real(real64), intent(in) :: x(:), y(:)",
        "logical, allocatable :: mask(:)",
        "integer :: i",
        "allocate(mask(size(x)))",
        "do i = 1, size(x)",
        "  mask(i) = any(y == x(i))",
        "end do",
        "end function ismember_vec_omat",
        "",
        "function intersect_vec_omat(x, y) result(z)",
        "real(real64), intent(in) :: x(:), y(:)",
        "real(real64), allocatable :: z(:)",
        "z = pack(unique_vec_omat(x), ismember_vec_omat(unique_vec_omat(x), unique_vec_omat(y)))",
        "end function intersect_vec_omat",
        "",
        "function union_vec_omat(x, y) result(z)",
        "real(real64), intent(in) :: x(:), y(:)",
        "real(real64), allocatable :: z(:)",
        "z = unique_vec_omat([x, y])",
        "end function union_vec_omat",
        "",
        "function setdiff_vec_omat(x, y) result(z)",
        "real(real64), intent(in) :: x(:), y(:)",
        "real(real64), allocatable :: ux(:)",
        "real(real64), allocatable :: z(:)",
        "ux = unique_vec_omat(x)",
        "z = pack(ux, .not. ismember_vec_omat(ux, unique_vec_omat(y)))",
        "end function setdiff_vec_omat",
        "",
        "function nonzeros_vec_omat(x) result(y)",
        "real(real64), intent(in) :: x(:)",
        "real(real64), allocatable :: y(:)",
        "y = pack(x, x /= 0.0_real64)",
        "end function nonzeros_vec_omat",
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
                "",
                "function logspace_omat(a, b, n) result(x)",
                "real(real64), intent(in) :: a, b",
                "integer, intent(in) :: n",
                "real(real64), allocatable :: x(:)",
                "x = 10.0_real64 ** linspace_omat(a, b, n)",
                "end function logspace_omat",
                "",
                "function colon2_omat(a, b) result(x)",
                "real(real64), intent(in) :: a, b",
                "real(real64), allocatable :: x(:)",
                "x = colon3_omat(a, 1.0_real64, b)",
                "end function colon2_omat",
                "",
                "function colon3_omat(a, step, b) result(x)",
                "real(real64), intent(in) :: a, step, b",
                "real(real64), allocatable :: x(:)",
                "integer :: i, n",
                "if (step == 0.0_real64) then",
                "  n = 0",
                "else if ((step > 0.0_real64 .and. a > b) .or. (step < 0.0_real64 .and. a < b)) then",
                "  n = 0",
                "else",
                "  n = int(floor((b - a) / step)) + 1",
                "end if",
                "allocate(x(max(0, n)))",
                "do i = 1, size(x)",
                "  x(i) = a + step * real(i - 1, real64)",
                "end do",
                "end function colon3_omat",
            ]
        )
    return select_helper_source(lines, body_lines)


def translate_source(source: str, generic: bool = False, source_path: Path | None = None) -> str:
    return Translator(generic=generic, source_path=source_path).translate(source)


def add_timing(timings: dict[str, float] | None, name: str, seconds: float) -> None:
    if timings is not None:
        timings[name] = timings.get(name, 0.0) + seconds


def print_timings(timings: dict[str, float], *, total: float) -> None:
    print("time:", file=sys.stderr)
    for name in ["read", "translate", "write", "setup", "compile", "run", "backend"]:
        value = timings.get(name)
        if value is not None:
            print(f"  {name + ':':<10}{value:9.6f} s", file=sys.stderr)
    print(f"  {'total:':<10}{total:9.6f} s", file=sys.stderr)


def validate_partial_source(source: str) -> None:
    translator = Translator()
    source = join_multiline_statements(source)
    for line_no, raw in enumerate(source.splitlines(), start=1):
        translator.add_line(raw, line_no)


def compile_and_run_capture(
    generated: str,
    compiler_name: str,
    emit_fortran: str | None = None,
    keep_path: Path | None = None,
    timings: dict[str, float] | None = None,
) -> ExecResult:
    compiler = shutil.which(compiler_name)
    if compiler is None:
        return ExecResult(2, "", "omat: gfortran not found; use --translate or -o to inspect generated Fortran\n")

    with tempfile.TemporaryDirectory(prefix="omat_") as tmp:
        tmpdir = Path(tmp)
        f90 = Path(emit_fortran) if emit_fortran else tmpdir / "omat_main.f90"
        exe = tmpdir / ("omat.exe" if sys.platform.startswith("win") else "omat.out")
        if not emit_fortran:
            start = time.perf_counter()
            f90.write_text(generated, encoding="utf-8")
            add_timing(timings, "setup", time.perf_counter() - start)
        start = time.perf_counter()
        build = subprocess.run([compiler, str(f90), "-o", str(exe)], text=True, capture_output=True)
        add_timing(timings, "compile", time.perf_counter() - start)
        if build.returncode != 0:
            return ExecResult(build.returncode, build.stdout, build.stderr)
        start = time.perf_counter()
        result = subprocess.run([str(exe)], text=True, capture_output=True)
        add_timing(timings, "run", time.perf_counter() - start)
        if keep_path is not None and not emit_fortran:
            start = time.perf_counter()
            keep_path.write_text(generated, encoding="utf-8")
            add_timing(timings, "write", time.perf_counter() - start)
            result.stderr += f"omat: kept generated Fortran in {keep_path}\n"
        return ExecResult(result.returncode, result.stdout, result.stderr)


def compile_and_run(
    generated: str,
    compiler_name: str,
    emit_fortran: str | None = None,
    keep_path: Path | None = None,
    timings: dict[str, float] | None = None,
) -> int:
    result = compile_and_run_capture(generated, compiler_name, emit_fortran, keep_path, timings)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def compile_generated_fortran(
    generated: str,
    compiler_name: str,
    fortran_path: Path,
    *,
    run_executable: bool,
    timings: dict[str, float] | None = None,
) -> int:
    compiler = shutil.which(compiler_name)
    if compiler is None:
        print("omat: gfortran not found; use --translate or -o to inspect generated Fortran", file=sys.stderr)
        return 2

    exe_path = fortran_path.with_suffix(".exe" if sys.platform.startswith("win") else ".out")
    try:
        start = time.perf_counter()
        fortran_path.write_text(generated, encoding="utf-8")
        add_timing(timings, "write", time.perf_counter() - start)
    except OSError as exc:
        print(f"omat: could not write {fortran_path}: {exc}", file=sys.stderr)
        return 1

    start = time.perf_counter()
    build = subprocess.run(
        [compiler, "-Wall", "-Wextra", str(fortran_path), "-o", str(exe_path)],
        text=True,
        capture_output=True,
    )
    add_timing(timings, "compile", time.perf_counter() - start)
    print(build.stdout, end="")
    print(build.stderr, end="", file=sys.stderr)
    if build.returncode != 0:
        return build.returncode

    print(f"omat: wrote {fortran_path}", file=sys.stderr)
    print(f"omat: compiled {exe_path}", file=sys.stderr)
    if not run_executable:
        return 0

    start = time.perf_counter()
    result = subprocess.run([str(exe_path)], text=True, capture_output=True)
    add_timing(timings, "run", time.perf_counter() - start)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_with_ofort(
    generated: str,
    ofort_path: str,
    keep_path: Path | None = None,
    timings: dict[str, float] | None = None,
) -> int:
    result = run_with_ofort_capture(generated, ofort_path, timings=timings)
    if keep_path is not None:
        start = time.perf_counter()
        keep_path.write_text(generated, encoding="utf-8")
        add_timing(timings, "write", time.perf_counter() - start)
        result.stderr += f"omat: kept generated Fortran in {keep_path}\n"
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_with_ofort_capture(
    generated: str,
    ofort_path: str,
    *,
    fast: bool = False,
    timings: dict[str, float] | None = None,
) -> ExecResult:
    ofort = Path(ofort_path)
    if not ofort.exists():
        found = shutil.which(ofort_path)
        if found is None:
            return ExecResult(2, "", f"omat: ofort not found: {ofort_path}\n")
        ofort = Path(found)
    with tempfile.TemporaryDirectory(prefix="omat_") as tmp:
        source = Path(tmp) / "omat_main.f90"
        start = time.perf_counter()
        source.write_text(generated, encoding="utf-8")
        add_timing(timings, "setup", time.perf_counter() - start)
        command = [str(ofort)]
        if fast:
            command.append("--fast")
        command.extend(["--no-warn-unused", str(source)])
        start = time.perf_counter()
        result = subprocess.run(command, text=True, capture_output=True)
        add_timing(timings, "run", time.perf_counter() - start)
        return ExecResult(result.returncode, result.stdout, result.stderr)


def line_opens_block(line: str) -> bool:
    stripped = strip_comment(line).strip()
    return FOR_RE.match(stripped) is not None or IF_RE.match(stripped) is not None


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


def run_repl_source(
    source_lines: list[str],
    ofort: str,
    summary: str | None = None,
    *,
    fast: bool = False,
) -> str | None:
    try:
        generated = translate_source("\n".join(source_lines))
    except OmatError as exc:
        print(f"omat: {exc}", file=sys.stderr)
        return None
    result = run_with_ofort_capture(generated, ofort, fast=fast)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        return None
    if summary is not None:
        print(summary, end="")
    else:
        print(result.stdout, end="")
    return result.stdout


def run_repl_buffer(buffer: list[str], ofort: str, *, fast: bool = False) -> str | None:
    return run_repl_source(buffer, ofort, fast=fast)


def run_repl_candidate(
    buffer: list[str],
    line: str,
    ofort: str,
    scalar_values: dict[str, float],
    materialize_limit: int,
    *,
    fast: bool = False,
) -> str | None:
    source_lines = [suppress_repl_output(prior) for prior in buffer]
    summary = summarize_repl_assignment(line, scalar_values, materialize_limit)
    source_lines.append(suppress_repl_output(line) if summary is not None else line)
    return run_repl_source(source_lines, ofort, summary, fast=fast)


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
        summary = summarize_repl_assignment(materialized_line, scalar_values, materialize_rand_limit)
        stored_line = suppress_repl_output(materialized_line) if summary is not None else materialized_line
        candidate = [*buffer, stored_line]
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
        "--compile",
        action="store_true",
        help=(
            "write generic Fortran and compile it with gfortran -Wall -Wextra; "
            "runs the executable only when --run is also given"
        ),
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
    parser.add_argument("--time", action="store_true", help="print translation/backend wall times to stderr")
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
    total_start = time.perf_counter()
    timings: dict[str, float] | None = {} if args.time else None
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
            args.compile,
            args.time,
            args.ofort_out,
            args.generic_out,
        ]
        if any(source_options):
            print(
                "omat: source file is required with translation, output, run, generic, compile, time, or keep options",
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
        start = time.perf_counter()
        source_text = source_path.read_text(encoding="utf-8")
        add_timing(timings, "read", time.perf_counter() - start)
    except OSError as exc:
        print(f"omat: could not read {source_path}: {exc}", file=sys.stderr)
        return 1

    generated_cache: dict[bool, str] = {}

    def generated_for(generic: bool) -> str:
        if generic not in generated_cache:
            start = time.perf_counter()
            generated_cache[generic] = translate_source(
                source_text,
                generic=generic,
                source_path=source_path,
            )
            add_timing(timings, "translate", time.perf_counter() - start)
        return generated_cache[generic]

    try:
        if args.compile:
            compile_output = Path(output_path) if output_path else source_path.with_name(f"{source_path.stem}_temp.f90")
            if args.ofort_out:
                start = time.perf_counter()
                Path(args.ofort_out).write_text(generated_for(False), encoding="utf-8")
                add_timing(timings, "write", time.perf_counter() - start)
            if args.generic_out:
                start = time.perf_counter()
                Path(args.generic_out).write_text(generated_for(True), encoding="utf-8")
                add_timing(timings, "write", time.perf_counter() - start)
            status = compile_generated_fortran(
                generated_for(True),
                args.gfortran,
                compile_output,
                run_executable=args.run,
                timings=timings,
            )
            if timings is not None:
                print_timings(timings, total=time.perf_counter() - total_start)
            return status
        active_generated = generated_for(args.generic)
        if args.ofort_out:
            start = time.perf_counter()
            Path(args.ofort_out).write_text(generated_for(False), encoding="utf-8")
            add_timing(timings, "write", time.perf_counter() - start)
        if args.generic_out:
            start = time.perf_counter()
            Path(args.generic_out).write_text(generated_for(True), encoding="utf-8")
            add_timing(timings, "write", time.perf_counter() - start)
        if output_path:
            start = time.perf_counter()
            Path(output_path).write_text(active_generated, encoding="utf-8")
            add_timing(timings, "write", time.perf_counter() - start)
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
        if timings is not None:
            print_timings(timings, total=time.perf_counter() - total_start)
        return 0

    keep_path = source_path.with_suffix(".f90") if args.keep else None
    if args.generic:
        status = compile_and_run(active_generated, args.gfortran, output_path, keep_path, timings)
        if timings is not None:
            print_timings(timings, total=time.perf_counter() - total_start)
        return status
    if "use ofort_la_mod" in active_generated or "use ofort_random_mod" in active_generated:
        status = run_with_ofort(active_generated, args.ofort, keep_path, timings)
        if timings is not None:
            print_timings(timings, total=time.perf_counter() - total_start)
        return status
    status = compile_and_run(active_generated, args.gfortran, output_path, keep_path, timings)
    if timings is not None:
        print_timings(timings, total=time.perf_counter() - total_start)
    return status


if __name__ == "__main__":
    raise SystemExit(run())
