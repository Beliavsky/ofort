from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"
CASES = ROOT / "tests" / "cases"


@pytest.fixture(scope="session", autouse=True)
def build_ofort():
    result = subprocess.run(
        ["make"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert OFORT.exists()


def case_files():
    return sorted(
        source for source in CASES.glob("*.f90")
        if source.name not in {"xsub.f90"}
    )


@pytest.mark.parametrize("source", case_files(), ids=lambda p: p.stem)
def test_case_stdout(source):
    expected = source.with_suffix(".out").read_text(encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == expected


def test_xsub_random_statistics():
    source = CASES / "xsub.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""

    parts = result.stdout.split()
    assert len(parts) == 3
    n = int(parts[0])
    mean = float(parts[1])
    sd = float(parts[2])

    assert n == 100
    assert 0.0 <= mean < 1.0
    assert 0.0 <= sd < 0.6
