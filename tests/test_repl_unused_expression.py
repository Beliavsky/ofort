"""Immediate expression reads count as uses without being saved as source."""
from pathlib import Path
import subprocess


OFORT = Path(__file__).resolve().parents[1] / "ofort.exe"


def run_repl(tmp_path, source):
    return subprocess.run(
        [str(OFORT), "--repl", "--nologo", "--prompt", ""],
        cwd=tmp_path, input=source, text=True, capture_output=True, timeout=10,
    )


def test_expression_read_prevents_unused_warning_on_save(tmp_path):
    result = run_repl(tmp_path, "integer i, j\ni = 2\nj = 3\ni**5\n.save saved.f90\n.quit!\n")
    assert result.returncode == 0, result.stderr
    assert "32" in result.stdout
    assert "variable 'i' declared but never used" not in result.stderr
    assert "variable 'j' declared but never used" in result.stderr
    assert "i**5" not in (tmp_path / "saved.f90").read_text(encoding="utf-8")


def test_expression_read_prevents_unused_warning_on_quit(tmp_path):
    result = run_repl(tmp_path, "integer i\ni = 2\ni**5\nquit\n")
    assert result.returncode == 0, result.stderr
    assert "32" in result.stdout
    assert "declared but never used" not in result.stderr


def test_clear_resets_expression_reads(tmp_path):
    result = run_repl(tmp_path, "integer i\ni = 2\ni**5\n.clear\ninteger i\ni = 3\n.save saved.f90\n.quit!\n")
    assert result.returncode == 0, result.stderr
    assert "variable 'i' declared but never used" in result.stderr


def test_rename_preserves_expression_reads(tmp_path):
    result = run_repl(tmp_path, "integer i\ni = 2\ni**5\n.rename i j\n.unused\n.save saved.f90\n.quit!\n")
    assert result.returncode == 0, result.stderr
    assert "unused declarations: (none)" in result.stdout
    assert "declared but never used" not in result.stderr
