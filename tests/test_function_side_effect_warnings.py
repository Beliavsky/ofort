from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_source(tmp_path, declaration, statement, options):
    source = tmp_path / "xfunction_side_effects.f90"
    source.write_text(
        "program main\nimplicit none\ninteger :: x, y\nx = 3\n"
        "y = f(x)\nprint *, y\ncontains\ninteger function f(x) result(y)\n"
        + declaration + "\n" + statement + "\ny = x\nend function f\nend program main\n",
        encoding="utf-8",
    )
    return subprocess.run([str(ROOT / "ofort.exe"), "--no-warn-unused",
                           "--no-warn-intrinsic-shadow", *options, str(source)],
                          cwd=tmp_path, text=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("intent", ["out", "inout"])
def test_function_output_argument_warning(tmp_path, fast, intent):
    options = ["--warn-function-side-effects"] + (["--fast"] if fast else [])
    result = run_source(tmp_path, f"integer, intent({intent}) :: x", "x = 7", options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["7"]
    assert f"function 'f' has INTENT({intent.upper()}) argument 'x'" in result.stderr
    assert "consider using a subroutine" in result.stderr


@pytest.mark.parametrize("options", [
    [],
    ["--warn-function-side-effects", "--no-warn-function-side-effects"],
    ["--warn-function-side-effects", "-w"],
    ["--warn-function-side-effects", "--fast", "-w"],
    ["-w", "--fast", "--warn-function-side-effects"],
])
def test_function_output_warning_suppressed(tmp_path, options):
    result = run_source(tmp_path, "integer, intent(inout) :: x", "x = 7", options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "consider using a subroutine" not in result.stderr


@pytest.mark.parametrize("declaration,statement", [
    ("integer, intent(in) :: x", ""),
    ("integer, value :: x", "x = 7"),
])
def test_function_input_or_value_argument_not_warned(tmp_path, declaration, statement):
    result = run_source(tmp_path, declaration, statement, ["--warn-function-side-effects"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "consider using a subroutine" not in result.stderr


@pytest.mark.parametrize("fast", [False, True])
def test_function_side_effect_warning_as_error(tmp_path, fast):
    result = run_source(tmp_path, "integer, intent(inout) :: x", "x = 7",
                        ["--warn-function-side-effects", "-Werror"] +
                        (["--fast"] if fast else []))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "consider using a subroutine" in result.stderr


def test_function_side_effect_warning_after_fast_option(tmp_path):
    result = run_source(tmp_path, "integer, intent(inout) :: x", "x = 7",
                        ["--fast", "--warn-function-side-effects"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "consider using a subroutine" in result.stderr
