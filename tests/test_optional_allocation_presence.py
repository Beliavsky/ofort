from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("xoptional_unallocated_actual_pending", "absent\npresent 3 60\nabsent"),
    ("xoptional_allocation_presence_pending", "T F\n-1\nT T\n0\n3\n-1\n7"),
    ("xoptional_keyword_forward_pending", "F F F 0\nF F T 30\nT F T 40\nT T T 60"),
])
def test_optional_allocation_presence(case, expected, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    source = ROOT / "tests" / "cases" / (case + ".f90")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        line.split() for line in expected.splitlines()
    ]
