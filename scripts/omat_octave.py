#!/usr/bin/env python3
"""Compare omat output with GNU Octave output for MATLAB/Octave scripts."""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OMAT = ROOT / "scripts" / "omat.py"
FUNCTION_RE = re.compile(
    r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(
    r"""
    (?<![A-Za-z_])
    [+-]?
    (?:
        (?:\d+\.\d*|\.\d+|\d+)
        (?:[eEdD][+-]?\d+)?
      | Inf(?:inity)?
      | NaN
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize_number(token: str, int_tol: float, decimals: int | None) -> str:
    text = token.replace("d", "e").replace("D", "E")
    try:
        value = float(text)
    except ValueError:
        return token
    if not math.isfinite(value):
        return token.lower()
    if abs(value) <= int_tol:
        return "0"
    nearest = round(value)
    if abs(value - nearest) <= int_tol:
        return str(int(nearest))
    if decimals is not None:
        out = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    else:
        out = f"{value:.12g}".lower()
        if "e" not in out and "." in out:
            out = out.rstrip("0").rstrip(".")
    return "0" if out == "-0" else out


def normalize_text(text: str, int_tol: float, decimals: int | None) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line.strip())
        line = NUMBER_RE.sub(lambda m: normalize_number(m.group(0), int_tol, decimals), line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def numeric_tokens(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_RE.finditer(text):
        token = match.group(0).replace("d", "e").replace("D", "E")
        try:
            values.append(float(token))
        except ValueError:
            pass
    return values


def nonnumeric_text(text: str) -> str:
    text = NUMBER_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def run_command(
    command: list[str],
    timeout: float | None,
    *,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def split_octave_local_functions(source_text: str) -> tuple[list[str], dict[str, list[str]]]:
    main_lines: list[str] = []
    functions: dict[str, list[str]] = {}
    lines = source_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = FUNCTION_RE.match(line)
        if match is None:
            main_lines.append(line)
            i += 1
            continue
        result, name, arg_text = match.groups()
        body: list[str] = [f"function {result} = {name}({arg_text})"]
        depth = 0
        i += 1
        while i < len(lines):
            raw = lines[i]
            low = raw.strip().lower()
            if low in {"end", "endfunction"} and depth == 0:
                body.append("endfunction")
                break
            body.append(raw)
            if re.match(r"^\s*(for|if|while)\b", raw, re.IGNORECASE):
                depth += 1
            elif low in {"end", "endfor", "endif", "endwhile"}:
                depth = max(0, depth - 1)
            i += 1
        if i >= len(lines):
            raise ValueError(f"function '{name}' is missing END")
        functions[name] = body
        i += 1
    return main_lines, functions


def prepare_octave_source(source: Path, workdir: Path) -> Path:
    source_text = source.read_text(encoding="utf-8-sig")
    main_lines, functions = split_octave_local_functions(source_text)
    main_name = source.stem
    main_path = workdir / f"{main_name}.m"
    main_path.write_text("\n".join(main_lines) + "\n", encoding="utf-8")
    for name, body in functions.items():
        (workdir / f"{name}.m").write_text("\n".join(body) + "\n", encoding="utf-8")
    return main_path


def outputs_match(
    omat_stdout: str,
    octave_stdout: str,
    *,
    rtol: float,
    atol: float,
    int_tol: float,
    decimals: int | None,
) -> bool:
    if normalize_text(omat_stdout, int_tol, decimals) == normalize_text(octave_stdout, int_tol, decimals):
        return True
    if nonnumeric_text(omat_stdout) != nonnumeric_text(octave_stdout):
        return False
    left = numeric_tokens(omat_stdout)
    right = numeric_tokens(octave_stdout)
    if len(left) != len(right):
        return False
    return all(math.isclose(a, b, rel_tol=rtol, abs_tol=atol) for a, b in zip(left, right))


def compare_source(args: argparse.Namespace, source: Path) -> bool:
    omat_cmd = [sys.executable, str(args.omat), str(source)]
    tempdir_obj = tempfile.TemporaryDirectory(prefix="omat_octave_")
    tempdir = Path(tempdir_obj.name)
    try:
        octave_source = prepare_octave_source(source, tempdir)
        octave_cmd = [args.octave, "--quiet", str(octave_source)]
        omat = run_command(omat_cmd, args.timeout)
        octave = run_command(octave_cmd, args.timeout, cwd=tempdir)
    except subprocess.TimeoutExpired as exc:
        tempdir_obj.cleanup()
        print(f"{source}: timed out after {exc.timeout} seconds", file=sys.stderr)
        return False
    except (OSError, ValueError) as exc:
        tempdir_obj.cleanup()
        print(f"{source}: {exc}", file=sys.stderr)
        return False
    finally:
        if not args.keep:
            tempdir_obj.cleanup()

    ok = (
        omat.returncode == octave.returncode
        and outputs_match(
            omat.stdout,
            octave.stdout,
            rtol=args.rtol,
            atol=args.atol,
            int_tol=args.int_tol,
            decimals=args.decimals,
        )
    )
    if args.pretty or not ok:
        print(f"==> {source}")
        print("omat")
        normalized = normalize_text(omat.stdout, args.int_tol, args.decimals)
        if normalized:
            print(normalized)
        if omat.stderr:
            print("stderr:")
            print(omat.stderr.rstrip())
        print(f"exit code: {omat.returncode}")
        print()
        print("octave")
        normalized = normalize_text(octave.stdout, args.int_tol, args.decimals)
        if normalized:
            print(normalized)
        if octave.stderr:
            print("stderr:")
            print(octave.stderr.rstrip())
        print(f"exit code: {octave.returncode}")
    elif args.verbose:
        print(f"{source}: ok")
    if args.keep:
        print(f"kept Octave work directory: {tempdir}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare omat output against GNU Octave.")
    parser.add_argument("sources", nargs="+", type=Path, help="MATLAB/Octave source files")
    parser.add_argument("--omat", type=Path, default=DEFAULT_OMAT, help="Path to scripts/omat.py")
    parser.add_argument(
        "--octave",
        default=shutil.which("octave-cli") or shutil.which("octave") or "octave.exe",
        help="Octave executable (prefer the command-line executable when available)",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout per source")
    parser.add_argument("--rtol", type=float, default=1e-5, help="Relative tolerance for numeric output")
    parser.add_argument("--atol", type=float, default=1e-5, help="Absolute tolerance for numeric output")
    parser.add_argument("--int-tol", type=float, default=1e-5, help="Tolerance for pretty integer rounding")
    parser.add_argument("--decimals", type=int, default=None, help="Round pretty numeric output")
    parser.add_argument("--pretty", action="store_true", help="Print normalized omat and Octave output")
    parser.add_argument("--verbose", action="store_true", help="Print passing file names")
    parser.add_argument("--keep", action="store_true", help="Keep temporary Octave files")
    args = parser.parse_args(argv)

    if args.decimals is not None and args.decimals < 0:
        parser.error("--decimals must be nonnegative")

    all_ok = True
    for source in args.sources:
        if not source.exists():
            print(f"{source}: file not found", file=sys.stderr)
            all_ok = False
            continue
        all_ok = compare_source(args, source) and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
