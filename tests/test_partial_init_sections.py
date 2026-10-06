from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected,unset_index", [
    ("contiguous_set", "7.0 9.0", None),
    ("contiguous_unset", None, 1),
    ("sum_set", "16.0", None),
    ("sum_unset", None, 1),
    ("strided_set", "9.0 7.0", None),
    ("strided_unset", None, 4),
    ("vector_set", "9.0 7.0", None),
    ("vector_unset", None, 4),
])
def test_partial_initialization_section(case, expected, unset_index, fast, tmp_path):
    source = ROOT / "tests" / "cases" / (
        f"xpartial_init_section_{case}_pending.f90"
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
        assert f"selected element at linear index {unset_index} is unset" in result.stderr
        assert "line 5: print *, " in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == expected.split()
