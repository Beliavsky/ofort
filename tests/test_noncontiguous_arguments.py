from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("explicit", "1 12 3 24 5 36 7 48\n400 12 300 24 200 36 100 48"),
    ("assumed", "0 -2 1 -1 2 2\n1 212 3 114 5 6 7 8 9 230 11 132 13 14 15 16"),
    ("forward", "1 2 3 104 5 6 7 208 9 10\n250\n10 2 30 104 50 6 70 208 90 10"),
    ("contiguous", "T 4\n101 2 103 4 105 6 107 8\nT 4\n101 40 103 30 105 20 107 10"),
])
def test_noncontiguous_argument_copyback(case, expected, fast, tmp_path):
    source = ROOT / "tests" / "cases" / f"xnoncontig_{case}_pending.f90"
    command = [str(ROOT / "ofort.exe"), "-w", "--check-uninitialized"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        line.split() for line in expected.splitlines()
    ]
