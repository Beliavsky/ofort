"""Default input follows INPUT_UNIT when it has an explicit connection."""
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
def test_input_unit_redirect(tmp_path, fast):
    source = ROOT / "tests/cases/xinput_unit_redirect_pending.f90"
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path, input="",
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.split() == ["17", "29"]
    assert result.stderr == ""


@pytest.mark.parametrize("fast", [False, True])
def test_input_unit_stdin_fallback(tmp_path, fast):
    source = tmp_path / "stdin.f90"
    source.write_text(
        "program test\nuse iso_fortran_env, only: input_unit\n"
        "implicit none\ninteger :: a, b\nread(*,*) a\n"
        "read(input_unit,*) b\nprint *, a, b\nend program test\n",
        encoding="utf-8",
    )
    command = [str(ROOT / "ofort.exe"), "-w"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path, input="17\n29\n",
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["17", "29"]
    assert result.stderr == ""
