from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("random", "element_set", "T"),
    ("random", "element_unset", None),
    ("random", "section_set", "T"),
    ("random", "section_unset", None),
    ("random", "strided_set", "T"),
    ("random", "strided_unset", None),
    ("random", "partial_sum", None),
    ("random", "full", "T"),
    ("elemental", "out_section_set", "7.0 7.0"),
    ("elemental", "out_section_unset", None),
    ("elemental", "out_section_sum", None),
    ("elemental", "out_mixed_set", "7.0"),
    ("elemental", "out_mixed_unset", None),
    ("elemental", "out_outside", "1.0 1.0"),
    ("elemental", "inout_preserve", "7.0 1.0"),
    ("elemental", "full", "28.0"),
]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("group,case,expected", CASES)
def test_partial_initialization_output(group, case, expected, fast, tmp_path):
    source = ROOT / "tests" / "cases" / f"xpartial_init_{group}_{case}_pending.f90"
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    if expected is None:
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stdout == ""
        assert "Variable 'a' is used before it is" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == expected.split()
