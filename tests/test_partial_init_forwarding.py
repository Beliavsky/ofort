from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("procedure", ["function", "subroutine"])
@pytest.mark.parametrize("case", ["set", "unset", "sum", "inquiry"])
def test_partial_initialization_forwarding(procedure, case, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_forward_{procedure}_{case}_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if case in ("unset", "sum"):
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'x' is used before it is" in result.stderr
        expression = "x(1)" if case == "unset" else "sum(x)"
        statement = ("y = " if procedure == "function" else "print *, ") + expression
        assert "line 13: " + statement in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        expected = "7.0" if case == "set" else (
            "4" if procedure == "function" else "2 2"
        )
        assert result.stdout.split() == expected.split()
