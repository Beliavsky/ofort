from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    (intent, association, case)
    for intent in ("inout", "out")
    for association in ("whole", "section")
    for case in ("set", "unset", "sum", "complete",
                 "preserve" if intent == "inout" else "outside")
]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("intent,association,case", CASES)
def test_partial_initialization_function_array(intent, association, case, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_function_array_{intent}_{association}_{case}_pending.f90"
    )
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if case in ("unset", "sum"):
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'a' is used before it is" in result.stderr
        if case == "unset":
            expression = "a(1)" if association == "whole" else "a(2)"
        else:
            expression = "sum(a)" if association == "whole" else "sum(a(2:4))"
        assert "print *, " + expression in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        expected = {
            "set": "7.0",
            "complete": "21.0",
            "preserve": "5.0 7.0",
            "outside": "11.0" if association == "whole" else "1.0 1.0",
        }[case]
        assert result.stdout.split() == expected.split()
