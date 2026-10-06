from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"


@pytest.mark.parametrize("fast", [False, True])
def test_open_unit_limit_returns_iostat_and_reuses_closed_slot(tmp_path, fast):
    source = tmp_path / "handled.f90"
    source.write_text('''program handled
implicit none
integer :: i, j, ios, failed_unit
logical :: opened
character(len=40) :: filename
failed_unit = 0
do i = 100, 227
   write(filename, '(a,i0,a)') 'unit_', i, '.txt'
   open(unit=i, file=trim(filename), status='replace', iostat=ios)
   if (ios /= 0) then
      failed_unit = i
      exit
   end if
end do
if (failed_unit == 0) error stop 'limit not reached'
inquire(unit=failed_unit, opened=opened)
if (opened) error stop 'failed unit connected'
! Reopening an existing unit must not consume another slot.
open(unit=100, file='unit_100.txt', iostat=ios)
if (ios /= 0) error stop 'existing connection rejected'
print *, 'handled'
close(100, status='delete')
open(unit=999, file='reused.txt', status='replace', iostat=ios)
if (ios /= 0) error stop 'closed slot not reused'
close(999, status='delete')
do j = 101, failed_unit - 1
   close(j, status='delete')
end do
print *, 'reused'
end program handled
''', encoding="utf-8")
    command = [str(OFORT), "-w"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["handled", "reused"]


@pytest.mark.parametrize("fast", [False, True])
def test_open_unit_limit_without_iostat_is_fatal(tmp_path, fast):
    source = tmp_path / "unhandled.f90"
    source.write_text('''program unhandled
implicit none
integer :: i
character(len=40) :: filename
do i = 100, 227
   write(filename, '(a,i0,a)') 'unit_', i, '.txt'
   open(unit=i, file=trim(filename), status='replace')
end do
end program unhandled
''', encoding="utf-8")
    command = [str(OFORT), "-w"]
    if fast:
        command.append("--fast")
    result = subprocess.run(command + [str(source)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert "Too many open units" in result.stderr
