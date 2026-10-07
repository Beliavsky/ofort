from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("procedure", ["function", "subroutine"])
@pytest.mark.parametrize("case", ["set", "unset", "inquiry"])
def test_partial_initialization_mixed_dummy(procedure, case, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_mixed_dummy_{procedure}_{case}_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if case == "unset":
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'x' is used before it is" in result.stderr
        statement = "y = x(1)" if procedure == "function" else "print *, x(1)"
        assert "line 9: " + statement in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        expected = "7.0" if case == "set" else (
            "4" if procedure == "function" else "2 2"
        )
        assert result.stdout.split() == expected.split()
