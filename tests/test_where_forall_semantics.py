from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("xwhere_mask_capture_pending", "T\nT\nT\nT"),
    ("xwhere_nested_elsewhere_pending", "T\nT"),
    ("xforall_simultaneous_pending", "T\nT T\nT\nT\nT"),
])
def test_where_forall_semantics(case, expected, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    command.append(str(ROOT / "tests" / "cases" / (case + ".f90")))
    result = subprocess.run(command, cwd=tmp_path, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert [line.split() for line in result.stdout.splitlines()] == [
        line.split() for line in expected.splitlines()
    ]
