from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("xpointer_alias_chain_pending",
     "-2 0 10 6 2\n1000 600 2\n1 2 3 4 5 600 7 8 9 1000\n"
     "33 4 22 8 11\n1 33 3 4 5 22 7 8 9 11"),
    ("xpointer_result_forward_alias_pending",
     "1 2 3 40 5 60 7 80\n1 2 3 140 5 160 7 80\n2 140 160 80 80 160 140"),
    ("xpointer_component_chain_pending",
     "1 2 3 4 500 6 7 8\n7 500 300\n1 2 30 4 50 6 70 8\n1 30 50 70"),
    ("xpointer_remap_section_bounds",
     "T -1 1 20 40 60\n10 20 30 400 50 60"),
    ("xpointer_function_result_section",
     "T 3 20 40 60\n10 20 30 400 50 60"),
])
def test_pointer_alias_chain(case, expected, fast, tmp_path):
    command = [str(ROOT / "ofort.exe"), "-w"]
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
