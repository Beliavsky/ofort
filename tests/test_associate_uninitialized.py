"""Association permits metadata inquiries, but not reads of unset values."""
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("scenario", ["bounds", "read", "after", "index", "expression"])
def test_associate_uninitialized(tmp_path, fast, scenario):
    bodies = {
        "bounds": "associate(a => m, b => m(:,:))\n"
                  "print *, lbound(a), lbound(b), size(a), shape(b)\n"
                  "end associate\n",
        "read": "associate(a => m)\nprint *, a\nend associate\n",
        "after": "associate(a => m)\nprint *, size(a)\nend associate\nprint *, m\n",
        "index": "associate(a => m(i:,:))\nprint *, size(a)\nend associate\n",
        "expression": "associate(a => m + 1)\nprint *, size(a)\nend associate\n",
    }
    source = tmp_path / "associate.f90"
    source.write_text(
        "program test\nimplicit none\nreal :: m(-2:3,0:9)\ninteger :: i\n"
        + bodies[scenario] + "end program test\n", encoding="utf-8"
    )
    command = [str(ROOT / "ofort.exe")]
    if fast:
        command.append("--fast")
    command.extend(["-w", "--check-uninitialized", str(source)])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
    if scenario == "bounds":
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout.split() == ["-2", "0", "1", "1", "60", "6", "10"]
    else:
        assert result.returncode != 0
        assert "used before it is set" in result.stderr
