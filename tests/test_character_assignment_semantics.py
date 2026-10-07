"""Character section and substring assignment regressions."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,widths", [
    ("overlap_assignment", [1, 1, 1, 1, 1]),
    ("deferred_assignment", [3, 2, 2, 3, 2, 1, 2, 1]),
    ("result_length", [2, 2, 2, 2, 1, 1, 1]),
])
def test_character_assignment_semantics(case, widths, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    source = ROOT / "tests" / "cases" / f"xcharacter_{case}_pending.f90"
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        ["T"] * width for width in widths
    ]
