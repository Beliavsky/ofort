from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("association", ["whole", "section"])
@pytest.mark.parametrize("case,expected", [
    ("set", "7.0"),
    ("unset", None),
    ("sum", None),
    ("preserve", "5.0 7.0"),
    ("complete", "21.0"),
])
def test_partial_initialization_inout(association, case, expected, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_inout_{association}_{case}_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if expected is None:
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'a' is used before it is" in result.stderr
        expression = ("sum(a)" if association == "whole" else "sum(a(2:4))") if case == "sum" else (
            "a(1)" if association == "whole" else "a(2)"
        )
        assert "line 5: print *, " + expression in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == expected.split()
