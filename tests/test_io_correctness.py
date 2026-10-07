"""Regression coverage for internal records and list/nonadvancing input."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("internal_records", "T\nT T T\nT 1 2 3 4 5 6"),
    ("reversion_implied_do",
     "T 1 4 9\nT 16 25 36\nT 49 64 81\nT 1 4 9 16 25 36 49 64 81"),
    ("list_directed_fields", "T 10 10 -9 30 -9 -9\nT\nT\nT"),
    ("nonadvancing_status", "T 4 T\nT 2 T\nT 3 T\nT 0"),
])
def test_io_correctness(case, expected, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    command.append(str(ROOT / "tests" / "cases" / f"xio_{case}_pending.f90"))
    result = subprocess.run(command, cwd=tmp_path, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        line.split() for line in expected.splitlines()
    ]
