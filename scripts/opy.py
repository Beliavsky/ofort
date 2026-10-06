#!/usr/bin/env python3
"""Interactive Python-to-Fortran runner backed by xp2f and ofort."""

from __future__ import annotations

import argparse
import atexit
import ast
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import tokenize
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OFORT = ROOT / ("ofort.exe" if sys.platform.startswith("win") else "ofort")
DEFAULT_XP2F = Path(r"c:\python\Python-to-Fortran\xp2f.py")
DEFAULT_SESSION_FORTRAN = "opy_session.f90"
DEFAULT_GENERIC_SESSION_FORTRAN = "generic_session.f90"
_TRANSLATORS: dict[Path, subprocess.Popen[str]] = {}


def close_translators() -> None:
    for worker in _TRANSLATORS.values():
        if worker.stdin is not None:
            worker.stdin.close()
        try:
            worker.wait(timeout=2)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()
        if worker.stdout is not None:
            worker.stdout.close()
    _TRANSLATORS.clear()


atexit.register(close_translators)


def run_translator(xp2f: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Reuse bytecode and xp2f helper metadata in a process-isolated session."""
    xp2f = xp2f.resolve()
    worker = _TRANSLATORS.get(xp2f)
    if worker is None or worker.poll() is not None:
        worker = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).with_name("_opy_xp2f_worker.py")),
             str(xp2f), str(ROOT / "scripts" / "__pycache__" / "opy")],
            cwd=str(xp2f.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        )
        _TRANSLATORS[xp2f] = worker
    assert worker.stdin is not None and worker.stdout is not None
    try:
        worker.stdin.write(json.dumps(arguments) + "\n")
        worker.stdin.flush()
        response = worker.stdout.readline()
    except (BrokenPipeError, OSError) as exc:
        return subprocess.CompletedProcess(arguments, 1, "", f"xp2f worker failed: {exc}\n")
    if not response:
        return subprocess.CompletedProcess(arguments, 1, "", "xp2f worker exited without a result\n")
    result = json.loads(response)
    return subprocess.CompletedProcess(arguments, result["returncode"], result["stdout"], result["stderr"])


UNSUPPORTED_MODULE_MESSAGES = {
    "argparse": "Python module 'argparse' is not supported by opy",
    "asyncio": "Python module 'asyncio' is not supported by opy",
    "collections": "Python module 'collections' is not supported by opy",
    "csv": "Python module 'csv' is not supported by opy",
    "dataclasses": "Python module 'dataclasses' is not supported by opy",
    "datetime": "Python module 'datetime' is not supported by opy",
    "functools": "Python module 'functools' is not supported by opy",
    "glob": "Python module 'glob' is not supported by opy",
    "http": "Python module 'http' is not supported by opy",
    "itertools": "Python module 'itertools' is not supported by opy",
    "json": "Python module 'json' is not supported by opy",
    "multiprocessing": "Python module 'multiprocessing' is not supported by opy",
    "os": "Python module 'os' is not supported by opy",
    "pathlib": "Python module 'pathlib' is not supported by opy",
    "re": "Python module 're' is not supported by opy",
    "shutil": "Python module 'shutil' is not supported by opy",
    "socket": "Python module 'socket' is not supported by opy",
    "sqlite3": "Python module 'sqlite3' is not supported by opy",
    "subprocess": "Python module 'subprocess' is not supported by opy",
    "sys": "Python module 'sys' is not supported by opy",
    "threading": "Python module 'threading' is not supported by opy",
    "time": "Python module 'time' is not supported by opy",
    "typing": "Python module 'typing' is not supported by opy",
    "urllib": "Python module 'urllib' is not supported by opy",
}


@dataclass
class RunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    fortran: str = ""
    message: str = ""


@dataclass
class TimedRunResult:
    result: RunResult
    translate_seconds: float = 0.0
    fortran_seconds: float = 0.0


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
    source = canonicalize_numpy_aliases(lines)
    source = rewrite_numpy_random_scalar_normal(source)
    return "\n".join(expression_display_line(line) for line in source) + ("\n" if source else "")


def canonicalize_numpy_aliases(lines: list[str]) -> list[str]:
    aliases: set[str] = set()
    imported_numpy_names: dict[str, str] = {}
    out: list[str] = []
    for line in lines:
        try:
            tree = ast.parse(line, mode="exec")
        except SyntaxError:
            out.append(line)
            continue
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.Import):
            node = tree.body[0]
            changed = False
            new_aliases = []
            for alias in node.names:
                if alias.name == "numpy":
                    aliases.add(alias.asname or "numpy")
                    new_aliases.append(ast.alias(name="numpy", asname="np"))
                    changed = True
                else:
                    new_aliases.append(alias)
            if changed:
                out.append("import " + ", ".join(
                    name.name if name.asname is None else f"{name.name} as {name.asname}"
                    for name in new_aliases
                ))
                continue
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.ImportFrom):
            node = tree.body[0]
            if node.module == "numpy":
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imported_numpy_names[alias.asname or alias.name] = alias.name
                aliases.add("np")
                out.append("import numpy as np")
                continue
        updated = line
        for alias in sorted(aliases - {"np"}, key=len, reverse=True):
            updated = re.sub(rf"\b{re.escape(alias)}\s*\.", "np.", updated)
        for local_name, numpy_name in sorted(imported_numpy_names.items(), key=lambda item: len(item[0]), reverse=True):
            updated = re.sub(
                rf"\b{re.escape(local_name)}\s*\(",
                f"np.{numpy_name}(",
                updated,
            )
        out.append(updated)
    return out


def rewrite_numpy_random_scalar_normal(lines: list[str]) -> list[str]:
    return [rewrite_numpy_random_scalar_normal_line(line) for line in lines]


def rewrite_numpy_random_scalar_normal_line(line: str) -> str:
    try:
        tree = ast.parse(line, mode="exec")
    except SyntaxError:
        return line
    tree = ScalarNormalRewriter().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:
        return line


class ScalarNormalRewriter(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if dotted_call_name(node.func) != "np.random.normal":
            return node
        if any(keyword.arg == "size" for keyword in node.keywords):
            return node
        if len(node.args) >= 3:
            return node

        loc = node.args[0] if len(node.args) >= 1 else ast.Constant(value=0.0)
        scale = node.args[1] if len(node.args) >= 2 else ast.Constant(value=1.0)
        for keyword in node.keywords:
            if keyword.arg == "loc":
                loc = keyword.value
            elif keyword.arg == "scale":
                scale = keyword.value
            else:
                return node

        loc_text = ast.unparse(loc)
        scale_text = ast.unparse(scale)
        replacement = (
            f"({loc_text}) + ({scale_text}) * "
            "np.sqrt(-2.0 * np.log(np.random.uniform())) * "
            "np.cos(6.283185307179586 * np.random.uniform())"
        )
        return ast.copy_location(ast.parse(replacement, mode="eval").body, node)


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


def run_session(
    lines: list[str],
    *,
    xp2f: Path,
    ofort: str,
    fast: bool,
    keep_fortran: Path | None = None,
    normalize_program_name: bool = True,
    generic: bool = False,
    explain_helpers: bool = True,
    profile_procs: bool = False,
    source_dir: Path | None = None,
) -> RunResult:
    return run_session_timed(
        lines,
        xp2f=xp2f,
        ofort=ofort,
        fast=fast,
        keep_fortran=keep_fortran,
        normalize_program_name=normalize_program_name,
        generic=generic,
        explain_helpers=explain_helpers,
        profile_procs=profile_procs,
        source_dir=source_dir,
    ).result


def run_session_timed(
    lines: list[str],
    *,
    xp2f: Path,
    ofort: str,
    fast: bool,
    keep_fortran: Path | None = None,
    normalize_program_name: bool = True,
    generic: bool = False,
    explain_helpers: bool = True,
    profile_procs: bool = False,
    source_dir: Path | None = None,
) -> TimedRunResult:
    run_dir = source_dir if source_dir is not None else ROOT
    with tempfile.TemporaryDirectory(prefix="opy_") as td:
        tmp = Path(td)
        f90_path = keep_fortran if keep_fortran is not None else tmp / "opy_session.f90"
        translate_start = time.perf_counter()
        translated = translate_session_to_path(
            lines,
            xp2f=xp2f,
            f90_path=f90_path,
            py_path=tmp / "opy_session.py",
            normalize_program_name=normalize_program_name,
            generic=generic,
            explain_helpers=explain_helpers,
            source_dir=source_dir,
        )
        translate_seconds = time.perf_counter() - translate_start
        if not translated.ok:
            return TimedRunResult(translated, translate_seconds=translate_seconds)

        ofort_cmd = [ofort]
        if fast:
            ofort_cmd.append("--fast")
        if profile_procs:
            ofort_cmd.append("--profile-procs")
        ofort_cmd.append(str(f90_path))
        fortran_start = time.perf_counter()
        ofort_run = subprocess.run(
            ofort_cmd,
            cwd=str(run_dir),
            text=True,
            capture_output=True,
        )
        fortran_seconds = time.perf_counter() - fortran_start
        return TimedRunResult(
            RunResult(
                ok=ofort_run.returncode == 0,
                stdout=ofort_run.stdout,
                stderr=ofort_run.stderr,
                fortran=translated.fortran,
                message="" if ofort_run.returncode == 0 else f"ofort exited with code {ofort_run.returncode}",
            ),
            translate_seconds=translate_seconds,
            fortran_seconds=fortran_seconds,
        )


def translate_session(
    lines: list[str],
    *,
    xp2f: Path,
    keep_fortran: Path | None = None,
    normalize_program_name: bool = True,
    generic: bool = False,
    explain_helpers: bool = True,
    source_dir: Path | None = None,
) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="opy_") as td:
        tmp = Path(td)
        f90_path = keep_fortran if keep_fortran is not None else tmp / "opy_session.f90"
        return translate_session_to_path(
            lines,
            xp2f=xp2f,
            f90_path=f90_path,
            py_path=tmp / "opy_session.py",
            normalize_program_name=normalize_program_name,
            generic=generic,
            explain_helpers=explain_helpers,
            source_dir=source_dir,
        )


def translate_session_to_path(
    lines: list[str],
    *,
    xp2f: Path,
    f90_path: Path,
    py_path: Path,
    normalize_program_name: bool,
    generic: bool = False,
    explain_helpers: bool = True,
    source_dir: Path | None = None,
) -> RunResult:
    unsupported_message = unsupported_module_message(lines)
    if unsupported_message:
        return RunResult(ok=False, message=unsupported_message)
    local_message = local_module_message(lines, source_dir)
    if local_message:
        return RunResult(ok=False, message=local_message)

    trailing_comments = python_trailing_assignment_comments(lines)
    source = repl_source(lines)
    syntax_message = python_syntax_message(source)
    if syntax_message:
        return RunResult(ok=False, message=syntax_message)
    py_path.write_text(source, encoding="utf-8")

    xp2f_run = run_translator(xp2f, [str(py_path.resolve()), "--out", str(f90_path.resolve())])
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
    fortran, unsupported_helpers = inline_ofort_helpers(
        fortran,
        generic=generic,
        explain_helpers=explain_helpers,
    )
    fortran = simplify_redundant_int_calls(fortran)
    if normalize_program_name:
        fortran = normalize_session_program_name(fortran)
    fortran = format_emitted_fortran(fortran)
    fortran = apply_python_trailing_comments(fortran, trailing_comments)
    if unsupported_helpers:
        helpers = ", ".join(unsupported_helpers)
        return RunResult(
            ok=False,
            fortran=fortran,
            message=(
                "generated Fortran requires unsupported xp2f helper"
                f"{'' if len(unsupported_helpers) == 1 else 's'}: {helpers}"
            ),
        )
    if fortran:
        f90_path.write_text(fortran, encoding="utf-8")

    if "use python_mod" in fortran.lower():
        return RunResult(
            ok=False,
            fortran=fortran,
            message=(
                "generated Fortran requires xp2f's python_mod helper; "
                "current ofort cannot run that helper module directly"
            ),
        )
    return RunResult(ok=True, fortran=fortran)


def python_trailing_assignment_comments(lines: list[str]) -> list[tuple[str, str, str]]:
    comments: list[tuple[str, str, str]] = []
    for line in lines:
        parsed = trailing_comment_for_line(line)
        if parsed is None:
            continue
        code, spacing, comment = parsed
        for name in assignment_target_names(code):
            comments.append((name.lower(), spacing, comment))
    return comments


def trailing_comment_for_line(line: str) -> tuple[str, str, str] | None:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(line).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                before_comment = line[: token.start[1]]
                code = before_comment.rstrip()
                spacing = before_comment[len(code) :]
                comment = token.string[1:].strip()
                if code and comment:
                    return code, spacing, comment
                return None
    except tokenize.TokenError:
        return None
    return None


def assignment_target_names(code: str) -> list[str]:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return []
    names: list[str] = []
    if len(tree.body) != 1:
        return names
    node = tree.body[0]
    if isinstance(node, ast.Assign):
        for target in node.targets:
            names.extend(simple_target_names(target))
    elif isinstance(node, ast.AnnAssign):
        names.extend(simple_target_names(node.target))
    elif isinstance(node, ast.AugAssign):
        names.extend(simple_target_names(node.target))
    return names


def simple_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(simple_target_names(elt))
        return names
    return []


def apply_python_trailing_comments(fortran: str, comments: list[tuple[str, str, str]]) -> str:
    if not comments:
        return fortran
    pending: dict[str, list[tuple[str, str]]] = {}
    for name, spacing, comment in comments:
        pending.setdefault(name, []).append((spacing, comment))

    out: list[str] = []
    for line in fortran.splitlines():
        updated = line
        if "!" not in line:
            match = re.match(r"\s*([A-Za-z_]\w*)\s*=", line)
            if match:
                name = match.group(1).lower()
                values = pending.get(name)
                if values:
                    spacing, comment = values.pop(0)
                    updated = f"{line}{spacing}! {comment}"
        out.append(updated)
    return "\n".join(out) + ("\n" if fortran.endswith("\n") else "")


def python_syntax_message(source: str) -> str:
    try:
        ast.parse(source, mode="exec")
    except IndentationError as exc:
        return format_python_syntax_error(exc, "invalid Python indentation")
    except SyntaxError as exc:
        return format_python_syntax_error(exc, "invalid Python syntax")
    return ""


def format_python_syntax_error(exc: SyntaxError, label: str) -> str:
    location = ""
    if exc.lineno is not None:
        location = f" at line {exc.lineno}"
        if exc.offset is not None:
            location += f", column {exc.offset}"
    message = f"{label}{location}: {exc.msg}"
    if exc.text and exc.text.strip():
        message += f"\nline {exc.lineno}: {exc.text.strip()}"
    return message


def unsupported_module_message(lines: list[str]) -> str:
    source = "\n".join(lines)
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return ""

    module_aliases: dict[str, str] = {}
    imported_names: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in UNSUPPORTED_MODULE_MESSAGES:
                    module_aliases[alias.asname or root_name] = root_name
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_name = node.module.split(".", 1)[0]
            if root_name in UNSUPPORTED_MODULE_MESSAGES:
                for alias in node.names:
                    if alias.name != "*":
                        imported_names[alias.asname or alias.name] = root_name

    if not module_aliases and not imported_names:
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            base = attribute_root_name(node)
            if base in module_aliases:
                return UNSUPPORTED_MODULE_MESSAGES[module_aliases[base]]
        elif isinstance(node, ast.Name) and node.id in imported_names:
            return UNSUPPORTED_MODULE_MESSAGES[imported_names[node.id]]
    return ""


def local_module_message(lines: list[str], source_dir: Path | None) -> str:
    if source_dir is None:
        return ""
    source = "\n".join(lines)
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return ""
    source_dir = source_dir.resolve()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                message = local_module_import_message(alias.name, source_dir)
                if message:
                    return message
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            message = local_module_import_message(node.module, source_dir)
            if message:
                return message
    return ""


def local_module_import_message(module_name: str, source_dir: Path) -> str:
    root_name = module_name.split(".", 1)[0]
    if root_name in {"numpy", "np"}:
        return ""
    local_file = source_dir / f"{root_name}.py"
    if local_file.exists():
        return (
            f"local module '{root_name}' is imported from {local_file}, "
            "but opy cannot translate local modules yet"
        )
    return ""


def attribute_root_name(node: ast.Attribute) -> str | None:
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def inline_ofort_helpers(
    fortran: str,
    *,
    generic: bool = False,
    explain_helpers: bool = True,
) -> tuple[str, list[str]]:
    helpers: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        imported = match.group(1).replace("&", "").replace("\n", " ")
        names = [name.strip().lower() for name in imported.split(",")]
        helpers.update(name for name in names if name)
        return ""

    updated = re.sub(
        r"^[ \t]*use[ \t]+python_mod[ \t]*,[ \t]*only[ \t]*:[ \t]*"
        r"((?:[^\n&]*&[ \t]*\r?\n[ \t]*&?[ \t]*)*[^\n&]*)[ \t]*$",
        repl,
        fortran,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    # Recent xp2f versions use generic names for these reductions.
    # Keep the existing one-dimensional helpers and generated-code spelling.
    aliases = {name: target for name, target in
               (("mean", "mean_1d"), ("var", "var_1d")) if name in helpers}
    if aliases:
        updated = re.sub(
            r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|![^\n]*)"
            r"|\b(mean|var)(?=\s*\()",
            lambda match: match.group(0) if match.group(1) else
            aliases.get(match.group(2).lower(), match.group(0)),
            updated,
            flags=re.IGNORECASE,
        )
        helpers = {aliases.get(name, name) for name in helpers}
    supported = {
        "arange_int",
        "cumsum_real",
        "linspace",
        "mean_1d",
        "np_amin",
        "np_amax",
        "ones_real",
        "rnorm",
        "runif",
        "std",
        "var_1d",
        "zeros_real",
    }
    unsupported = sorted(helpers - supported)
    if unsupported:
        return updated, unsupported
    needs_runif_scalar = bool(re.search(r"\brunif\s*\(\s*\)", updated))
    if needs_runif_scalar:
        updated = re.sub(r"\brunif\s*\(\s*\)", "runif_scalar()", updated)
    if "arange_int" in helpers:
        updated = add_contains_helper(updated, ARANGE_INT_HELPER, explain_helpers=explain_helpers)
    if "linspace" in helpers:
        updated = add_contains_helper(updated, LINSPACE_HELPER, explain_helpers=explain_helpers)
    if "zeros_real" in helpers:
        updated = add_contains_helper(updated, ZEROS_REAL_HELPER, explain_helpers=explain_helpers)
    if "ones_real" in helpers:
        updated = add_contains_helper(updated, ONES_REAL_HELPER, explain_helpers=explain_helpers)
    if "cumsum_real" in helpers:
        updated = add_contains_helper(updated, CUMSUM_REAL_HELPER, explain_helpers=explain_helpers)
    if "runif" in helpers:
        updated = add_contains_helper(updated, RUNIF_HELPER, explain_helpers=explain_helpers)
    if needs_runif_scalar:
        updated = add_contains_helper(updated, RUNIF_SCALAR_HELPER, explain_helpers=explain_helpers)
    if "rnorm" in helpers:
        if generic:
            updated = add_contains_helper(updated, RNORM_HELPER, explain_helpers=explain_helpers)
        else:
            line = "use ofort_random_mod, only: rnorm"
            if explain_helpers:
                comment = "provide standard normal random variates" if USE_LONG_HELPER_COMMENTS else "standard normal random variates"
                line += f"  ! {comment}"
            updated = add_use_statement(updated, line)
    if "mean_1d" in helpers or "std" in helpers or "var_1d" in helpers:
        updated = add_contains_helper(updated, MEAN_1D_HELPER, explain_helpers=explain_helpers)
    if "std" in helpers or "var_1d" in helpers:
        updated = add_contains_helper(updated, VAR_1D_HELPER, explain_helpers=explain_helpers)
    if "std" in helpers:
        updated = add_contains_helper(updated, STD_HELPER, explain_helpers=explain_helpers)
    for name, intrinsic in (("np_amin", "minval"), ("np_amax", "maxval")):
        if name in helpers:
            helper = f"""pure real(dp) function {name}(x)
use, intrinsic :: ieee_arithmetic, only: ieee_is_nan, ieee_value, ieee_quiet_nan
real(dp), intent(in) :: x(:)
if (any(ieee_is_nan(x))) then
  {name} = ieee_value(1.0_dp, ieee_quiet_nan)
else
  {name} = {intrinsic}(x)
end if
end function {name}"""
            updated = add_contains_helper(updated, helper, explain_helpers=explain_helpers)
    return updated, []


def add_use_statement(fortran: str, use_line: str) -> str:
    if re.search(rf"(?im)^\s*{re.escape(use_line)}\s*$", fortran):
        return fortran
    lines = fortran.splitlines()
    insert_at: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"\s*program\b", line, re.IGNORECASE):
            insert_at = i + 1
            continue
        if insert_at is not None:
            if not line.strip():
                continue
            if re.match(r"\s*use\b", line, re.IGNORECASE):
                insert_at = i + 1
                continue
            break
    if insert_at is None:
        return use_line + "\n" + fortran
    lines.insert(insert_at, use_line)
    return "\n".join(lines) + ("\n" if fortran.endswith("\n") else "")


def simplify_redundant_int_calls(fortran: str) -> str:
    integer_names = collect_default_integer_names(fortran)

    def repl(match: re.Match[str]) -> str:
        arg = match.group(1).strip()
        if arg.isdigit() or arg.lower() in integer_names:
            return arg
        return match.group(0)

    return re.sub(r"\bint\s*\(\s*([A-Za-z_]\w*|\d+)\s*\)", repl, fortran)


def normalize_session_program_name(fortran: str) -> str:
    fortran = re.sub(
        r"(?im)^(\s*program\s+)opy_session(\s*)$",
        r"\1main\2",
        fortran,
        count=1,
    )
    fortran = re.sub(
        r"(?im)^(\s*end\s+program\s+)opy_session(\s*)$",
        r"\1main\2",
        fortran,
        count=1,
    )
    return fortran


def collect_default_integer_names(fortran: str) -> set[str]:
    names: set[str] = set()
    for raw_line in fortran.splitlines():
        line = raw_line.split("!", 1)[0]
        match = re.match(r"\s*integer\s*(?P<attrs>,[^:]*)?::\s*(?P<decls>.+)$", line, re.IGNORECASE)
        if not match:
            continue
        attrs = (match.group("attrs") or "").lower()
        if "kind" in attrs or "(" in attrs:
            continue
        for decl in match.group("decls").split(","):
            name_match = re.match(r"\s*([A-Za-z_]\w*)", decl)
            if name_match:
                names.add(name_match.group(1).lower())
    return names


USE_LONG_HELPER_COMMENTS = False


SHORT_HELPER_COMMENTS = {
    "arange_int": "integers from start to stop-1",
    "zeros_real": "n zeros",
    "ones_real": "n ones",
    "cumsum_real": "cumulative sums",
    "runif": "n uniform random variates",
    "runif_scalar": "one uniform random variate",
    "rnorm": "n standard normal variates",
    "mean_1d": "arithmetic mean",
    "var_1d": "variance",
    "std": "standard deviation",
}


LONG_HELPER_COMMENTS = {
    "arange_int": "return integers from start to stop-1",
    "zeros_real": "return n zeros",
    "ones_real": "return n ones",
    "cumsum_real": "return cumulative sums",
    "runif": "return n uniform random variates",
    "runif_scalar": "return one uniform random variate",
    "rnorm": "return n standard normal variates",
    "mean_1d": "compute the arithmetic mean",
    "var_1d": "compute the variance",
    "std": "compute the standard deviation",
}


def helper_comments() -> dict[str, str]:
    return LONG_HELPER_COMMENTS if USE_LONG_HELPER_COMMENTS else SHORT_HELPER_COMMENTS


def add_contains_helper(fortran: str, helper: str, *, explain_helpers: bool = True) -> str:
    if explain_helpers:
        helper = explain_helper_signature(helper)
    if re.search(r"^\s*contains\s*$", fortran, flags=re.IGNORECASE | re.MULTILINE):
        fortran = normalize_contains_spacing(fortran)
        return re.sub(
            r"(?im)^\s*end\s+program\b",
            helper.rstrip() + "\nend program",
            fortran,
            count=1,
        )
    return re.sub(
        r"(?im)^\s*end\s+program\b",
        "contains\n\n" + helper.rstrip() + "\nend program",
        fortran,
        count=1,
    )


def explain_helper_signature(helper: str) -> str:
    lines = helper.splitlines()
    if not lines:
        return helper
    match = re.match(
        r"\s*(?:pure\s+)?(?:recursive\s+)?(?:[A-Za-z_][A-Za-z0-9_(),= ]+\s+)?"
        r"(?:function|subroutine)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        lines[0],
        re.IGNORECASE,
    )
    if not match:
        return helper
    name = match.group(1).lower()
    comment = helper_comments().get(name)
    if comment is None or "!" in lines[0]:
        return helper
    lines[0] = f"{lines[0]}  ! {comment}"
    return "\n".join(lines) + ("\n" if helper.endswith("\n") else "")


def normalize_contains_spacing(fortran: str) -> str:
    return re.sub(
        r"(?im)^([ \t]*contains[ \t]*)\n+",
        r"\1\n\n",
        fortran,
        count=1,
    )


def format_emitted_fortran(fortran: str) -> str:
    fortran = use_dp_alias(fortran)
    fortran = remove_xp2f_program_indent(fortran)
    fortran = remove_xp2f_comments(fortran)
    fortran = remove_blank_after_program(fortran)
    fortran = normalize_contains_spacing(fortran)
    return re.sub(
        r"(?im)^(end\s+(?:function|subroutine)\b[^\n]*\n)(?=[^\n]*\b(?:function|subroutine)\b)",
        r"\1\n",
        fortran,
    )


def remove_xp2f_comments(fortran: str) -> str:
    return re.sub(r"\s+!\s*constant from python source\s*$", "", fortran, flags=re.IGNORECASE | re.MULTILINE)


def remove_blank_after_program(fortran: str) -> str:
    return re.sub(r"(?im)^(\s*program\b[^\n]*\n)\s*\n", r"\1", fortran, count=1)


def remove_xp2f_program_indent(fortran: str) -> str:
    lines = fortran.splitlines()
    out: list[str] = []
    in_contains = False
    for line in lines:
        if re.match(r"\s*contains\s*$", line, re.IGNORECASE):
            in_contains = True
        if not in_contains and line.startswith("   "):
            out.append(line[3:])
        else:
            out.append(line)
    return "\n".join(out) + ("\n" if fortran.endswith("\n") else "")


def use_dp_alias(fortran: str) -> str:
    fortran = re.sub(
        r"(?im)^([ \t]*use,\s*intrinsic\s*::\s*iso_fortran_env,\s*only:\s*)real64([ \t]*)$",
        r"\1dp => real64\2",
        fortran,
    )
    fortran = re.sub(
        r"(?im)^[ \t]*integer,\s*parameter\s*::\s*dp\s*=\s*real64[ \t]*(?:!.*)?\n",
        "",
        fortran,
    )
    fortran = re.sub(r"\breal64\b", "dp", fortran)
    fortran = re.sub(r"\bdp\s*=>\s*dp\b", "dp => real64", fortran)
    fortran = re.sub(r"_real64\b", "_dp", fortran)
    return fortran


ARANGE_INT_HELPER = """\
function arange_int(start, stop, step) result(x)
integer, intent(in) :: start, stop, step
integer, allocatable :: x(:)
integer :: i, n
if (step == 0) error stop 'arange step cannot be zero'
if ((step > 0 .and. start >= stop) .or. (step < 0 .and. start <= stop)) then
  allocate(x(0))
  return
end if
n = ((stop - start - merge(1, -1, step > 0)) / step) + 1
allocate(x(n))
do i = 1, n
  x(i) = start + (i - 1) * step
end do
end function arange_int
"""


ZEROS_REAL_HELPER = """\
function zeros_real(n) result(x)
integer, intent(in) :: n
real(real64), allocatable :: x(:)
allocate(x(max(0, n)))
x = 0.0_real64
end function zeros_real
"""


ONES_REAL_HELPER = """\
function ones_real(n) result(x)
integer, intent(in) :: n
real(real64), allocatable :: x(:)
allocate(x(max(0, n)))
x = 1.0_real64
end function ones_real
"""


CUMSUM_REAL_HELPER = """\
function cumsum_real(x) result(y)
real(real64), intent(in) :: x(:)
real(real64), allocatable :: y(:)
integer :: i
allocate(y(size(x)))
if (size(x) <= 0) return
y(1) = x(1)
do i = 2, size(x)
  y(i) = y(i - 1) + x(i)
end do
end function cumsum_real
"""


RUNIF_HELPER = """\
function runif(n) result(x)
integer, intent(in) :: n
real(real64), allocatable :: x(:)
allocate(x(max(0, n)))
if (size(x) > 0) call random_number(x)
end function runif
"""


RUNIF_SCALAR_HELPER = """\
function runif_scalar() result(x)
real(real64) :: x
call random_number(x)
end function runif_scalar
"""


RNORM_HELPER = """\
function rnorm(n) result(x)
integer, intent(in) :: n
real(real64), allocatable :: x(:)
real(real64) :: u1, u2, pi
integer :: i
allocate(x(max(0, n)))
pi = acos(-1.0_real64)
i = 1
do while (i <= size(x))
  call random_number(u1)
  call random_number(u2)
  if (u1 <= 0.0_real64) cycle
  x(i) = sqrt(-2.0_real64 * log(u1)) * cos(2.0_real64 * pi * u2)
  if (i + 1 <= size(x)) then
    x(i + 1) = sqrt(-2.0_real64 * log(u1)) * sin(2.0_real64 * pi * u2)
  end if
  i = i + 2
end do
end function rnorm
"""


LINSPACE_HELPER = """\
function linspace(start, stop, num) result(x)
real(real64), intent(in) :: start, stop
integer, intent(in) :: num
real(real64), allocatable :: x(:)
integer :: i
allocate(x(max(0, num)))
if (num == 1) then
  x(1) = start
else if (num > 1) then
  do i = 1, num
    x(i) = start + (stop - start) * real(i - 1, real64) / real(num - 1, real64)
  end do
  x(num) = stop
end if
end function linspace
"""


MEAN_1D_HELPER = """\
pure real(real64) function mean_1d(x)
real(real64), intent(in) :: x(:)
if (size(x) <= 0) then
  mean_1d = 0.0_real64
else
  mean_1d = sum(x) / real(size(x), real64)
end if
end function mean_1d
"""


VAR_1D_HELPER = """\
pure real(real64) function var_1d(x, ddof)
real(real64), intent(in) :: x(:)
integer, intent(in), optional :: ddof
integer :: d, n
real(real64) :: mu
n = size(x)
if (present(ddof)) then
  d = ddof
else
  d = 0
end if
if (n <= d .or. n <= 0) then
  var_1d = 0.0_real64
  return
end if
mu = mean_1d(x)
var_1d = sum((x - mu)**2) / real(n - d, real64)
end function var_1d
"""


STD_HELPER = """\
pure real(real64) function std(x, ddof)
real(real64), intent(in) :: x(:)
integer, intent(in), optional :: ddof
integer :: d
if (present(ddof)) then
  d = ddof
else
  d = 0
end if
std = sqrt(var_1d(x, d))
end function std
"""


def print_incremental_output(previous: str, current: str) -> None:
    text = incremental_output_text(previous, current)
    if text:
        print(text, end="" if text.endswith("\n") else "\n")


def incremental_output_text(previous: str, current: str) -> str:
    if current.startswith(previous):
        text = current[len(previous) :]
    elif previous:
        previous_lines = previous.splitlines(keepends=True)
        current_lines = current.splitlines(keepends=True)
        if len(current_lines) >= len(previous_lines):
            text = "".join(current_lines[len(previous_lines) :])
        else:
            text = current
    else:
        text = current
    return text


def save_repl_file(path: str | None, text: str, label: str) -> None:
    if path is None or not text:
        return
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"opy: could not save {label}: {exc}", file=sys.stderr)
        return
    print(f"wrote {path}", file=sys.stderr)


def save_repl_session(
    lines: list[str],
    *,
    fortran: str,
    fortran_path: str | None,
    generic_fortran_path: str | None,
) -> None:
    if not lines or not fortran:
        return
    save_repl_file(fortran_path, fortran, "Fortran")
    save_repl_file(generic_fortran_path, generic_session_source(fortran), "generic Fortran")


def generic_session_source(fortran: str) -> str:
    return (
        "! Generated by opy.\n"
        "! This is currently the same source used for ofort execution after opy helper inlining.\n"
        + fortran
    )


def run_file(args: argparse.Namespace) -> int:
    source = Path(args.source)
    try:
        lines = source.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        print(f"opy: could not read {source}: {exc}", file=sys.stderr)
        return 1

    python_result: RunResult | None = None
    python_seconds = 0.0
    if args.time_both:
        python_result, python_seconds = run_python_source_timed(source)
        if python_result.stdout:
            print(python_result.stdout, end="" if python_result.stdout.endswith("\n") else "\n")
        if python_result.stderr:
            print(python_result.stderr, end="" if python_result.stderr.endswith("\n") else "\n", file=sys.stderr)
        if not python_result.ok and python_result.message:
            print(f"python: {python_result.message}", file=sys.stderr)

    timed_result = run_session_timed(
        lines,
        xp2f=Path(args.xp2f),
        ofort=args.ofort,
        fast=not args.no_fast,
        keep_fortran=Path(args.out) if args.out else None,
        normalize_program_name=False,
        generic=args.generic,
        explain_helpers=not args.no_explain,
        source_dir=source.parent,
    )
    result = timed_result.result
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if not result.ok:
        if result.message:
            print(f"opy: {result.message}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        if args.time or args.time_both:
            print_timing(
                timed_result,
                python_seconds=python_seconds if args.time_both else None,
                python_result=python_result,
            )
        return 1
    if args.time or args.time_both:
        print_timing(
            timed_result,
            python_seconds=python_seconds if args.time_both else None,
            python_result=python_result,
        )
    return 0


def run_python_source_timed(source: Path) -> tuple[RunResult, float]:
    start = time.perf_counter()
    try:
        python_run = subprocess.run(
            [sys.executable, str(source)],
            cwd=str(source.parent),
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return RunResult(ok=False, message="Python executable not found"), time.perf_counter() - start
    elapsed = time.perf_counter() - start
    return (
        RunResult(
            ok=python_run.returncode == 0,
            stdout=python_run.stdout,
            stderr=python_run.stderr,
            message="" if python_run.returncode == 0 else f"Python exited with code {python_run.returncode}",
        ),
        elapsed,
    )


def print_timing(
    timed_result: TimedRunResult,
    *,
    python_seconds: float | None,
    python_result: RunResult | None,
) -> None:
    if python_seconds is not None:
        status = "ok" if python_result is not None and python_result.ok else "failed"
        print("python timing:", file=sys.stderr)
        print(f"  run:    {python_seconds:.6f} s ({status})", file=sys.stderr)
    total = timed_result.translate_seconds + timed_result.fortran_seconds
    status = "ok" if timed_result.result.ok else "failed"
    print("opy timing:", file=sys.stderr)
    print(f"  translate:   {timed_result.translate_seconds:.6f} s", file=sys.stderr)
    print(f"  fortran run: {timed_result.fortran_seconds:.6f} s", file=sys.stderr)
    print(f"  total:       {total:.6f} s ({status})", file=sys.stderr)


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
            save_repl_session(
                lines,
                fortran=last_fortran,
                fortran_path=args.session_fortran,
                generic_fortran_path=args.generic_session_fortran,
            )
            return 0
        line = line.lstrip("\ufeffï»¿")
        command = line.strip().lower()
        if command in {"quit", "exit"}:
            save_repl_session(
                lines,
                fortran=last_fortran,
                fortran_path=args.session_fortran,
                generic_fortran_path=args.generic_session_fortran,
            )
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
            generic=args.generic,
            explain_helpers=not args.no_explain,
            source_dir=Path.cwd(),
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
    parser.add_argument(
        "--time",
        action="store_true",
        help="print opy translation and generated-Fortran run timings for source-file runs",
    )
    parser.add_argument(
        "--time-both",
        action="store_true",
        help="also run the original Python source and print Python and opy timings",
    )
    parser.add_argument(
        "--generic",
        action="store_true",
        help="generate portable generic Fortran helpers instead of ofort extension-module calls",
    )
    parser.add_argument(
        "--no-explain",
        action="store_true",
        help="omit brief explanatory comments on generated Fortran helper procedures",
    )
    parser.add_argument("-o", "--out", help="write generated Fortran to this path")
    parser.add_argument(
        "--session-fortran",
        default=DEFAULT_SESSION_FORTRAN,
        help=f"in REPL mode, save accepted session as Fortran on exit (default: {DEFAULT_SESSION_FORTRAN})",
    )
    parser.add_argument(
        "--generic-session-fortran",
        default=DEFAULT_GENERIC_SESSION_FORTRAN,
        help=f"in REPL mode, save generic Fortran on exit (default: {DEFAULT_GENERIC_SESSION_FORTRAN})",
    )
    parser.add_argument(
        "--no-save-session",
        action="store_true",
        help="in REPL mode, do not save generated Fortran on exit",
    )
    args = parser.parse_args()

    xp2f = Path(args.xp2f)
    if not xp2f.exists():
        print(f"opy: xp2f.py not found: {xp2f}", file=sys.stderr)
        return 1
    if args.source:
        return run_file(args)
    if args.no_save_session:
        args.session_fortran = None
        args.generic_session_fortran = None
    return run_repl(args)


if __name__ == "__main__":
    raise SystemExit(main())
