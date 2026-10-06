from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("procedure", ["function", "subroutine"])
@pytest.mark.parametrize("case", ["set", "unset"])
def test_partial_initialization_input_argument(procedure, case, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_in_{procedure}_{case}_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if case == "set":
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == ["7.0"]
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'x' is used before it is set" in result.stderr
        statement = "y = x" if procedure == "function" else "print *, x"
        assert "line 13: " + statement in result.stderr
