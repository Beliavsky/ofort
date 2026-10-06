from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("complete", "21.0"),
    ("element", "7.0"),
    ("sum", None),
    ("unset", None),
])
def test_partial_initialization_function_copyback(case, expected, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        "xpartial_init_function_" + case + "_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if expected is None:
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'a' is used before it is fully set" in result.stderr
        assert "first unset element is a(1)" in result.stderr
        statement = "sum(a)" if case == "sum" else "a(1)"
        assert "line 6: print *, " + statement in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == [expected]
