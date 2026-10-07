from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,checks_per_line", [
    ("allocatable", [2, 2, 2, 2, 2, 2, 2, 2, 2]),
    ("pointer", [1, 2, 1, 1, 2, 2, 1, 2]),
    ("overlap", [3, 3, 3, 2, 3, 2, 2, 2]),
])
def test_derived_copy_semantics(case, checks_per_line, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    source = ROOT / "tests" / "cases" / (
        "xderived_copy_" + case + "_pending.f90"
    )
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        ["T"] * count for count in checks_per_line
    ]
