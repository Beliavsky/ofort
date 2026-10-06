from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import pytest

from scripts.analyze_ofort_symbols import DEFAULT_SOURCE, build_report, keyword_name_test_source


ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"
CASES = ROOT / "tests" / "cases"
RUNNER = ROOT / "scripts" / "xofort.py"
OG_RUNNER = ROOT / "scripts" / "og.py"
PRUNE_RUNNER = ROOT / "scripts" / "ofort_prune.py"
CONCAT_MANIFEST = ROOT / "scripts" / "concat_manifest.py"
COMPILE_MANIFEST = ROOT / "scripts" / "compile_manifest.py"
XOFORT_MAKE = ROOT / "scripts" / "xofort_make.py"


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
    def has_text_expected_output(source):
        expected = source.with_suffix(".out")
        if not expected.exists():
            return False
        try:
            expected.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False
        return True

    return sorted(
        source for source in CASES.glob("*.f90")
        if has_text_expected_output(source)
        if source.name not in {
            "xinput_output_unit.f90",
            "xsub.f90",
            "ximplicit_none.f90",
            "xtype_change.f90",
            "xwrite_file.f90",
            "xwrite_file_alloc.f90",
            "xstream.f90",
            "xexit.f90",
            "xtyped_function.f90",
            "xtype_keyword_intrinsic.f90",
            "xrandom_print_array.f90",
            "ximplicit_default.f90",
            "xcpu_time.f90",
            "xdate_and_time.f90",
            "xtransfer.f90",
            "xsave.f90",
            "xentry_obsolescent.f90",
            "xalternate_return_obsolescent.f90",
            "xalternate_return_dummy_obsolescent.f90",
            "xallocate_already_allocated.f90",
            "ximplicit_derived_type.f90",
            "ximplicit_typing_ranges.f90",
            "xadvance_no.f90",
        }
    )


def test_keywords_can_be_variable_names_like_gfortran(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required as the keyword-name oracle")

    keywords = build_report(DEFAULT_SOURCE)["keywords"]
    source = tmp_path / "keyword_names.f90"
    exe = tmp_path / ("keyword_names.exe" if sys.platform.startswith("win") else "keyword_names")
    source.write_text(keyword_name_test_source(keywords), encoding="utf-8")

    gfortran_compile = subprocess.run(
        [gfortran, str(source), "-o", str(exe)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert gfortran_compile.returncode == 0, gfortran_compile.stdout + gfortran_compile.stderr

    expected = subprocess.run(
        [str(exe)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert expected.returncode == 0, expected.stdout + expected.stderr

    result = subprocess.run(
        [str(OFORT), "--no-warn-intrinsic-shadow", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == expected.stdout.split()


def test_intent_in_assignment_rejected_by_check(tmp_path):
    source = tmp_path / "xintent_in_assign.f90"
    source.write_text(
        """
module m
  implicit none
contains
  function f(i)
    integer, intent(in) :: i
    integer :: f
    i = 2*i
    f = i
  end function f
end module m

program main
  use m
  implicit none
  print *, f(3)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Cannot assign to INTENT(IN) argument 'i' in procedure 'f'" in result.stderr


def test_nondefinable_actual_for_modified_dummy_is_rejected(tmp_path):
    source = tmp_path / "xdefinable_arg.f90"
    source.write_text(
        """
subroutine sub(i)
integer :: i
if (i > 2) i = i + 1
end subroutine sub

program main
implicit none
integer :: i = 3
call sub(i)
call sub(3)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Actual argument for dummy argument 'i' of 'sub' is not definable" in result.stderr
    assert "call sub(3)" in result.stderr


def test_warn_unused_reports_assigned_but_unread_variable(tmp_path):
    source = tmp_path / "xwarn_unused.f90"
    source.write_text(
        """
program main
implicit none
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: save_seconds, load_seconds, total_seconds
save_seconds = 1.0_dp
load_seconds = 2.0_dp
total_seconds = save_seconds + load_seconds
print *, save_seconds, load_seconds
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1.0", "2.0"]
    assert "warning: variable 'total_seconds' declared but never used" in result.stderr
    assert "save_seconds' declared but never used" not in result.stderr
    assert "load_seconds' declared but never used" not in result.stderr
    assert "dp' declared but never used" not in result.stderr


def test_fast_recurrence_with_loop_dependent_coefficient(tmp_path):
    source = tmp_path / "xfast_loop_dependent_recurrence.f90"
    source.write_text(
        """
module m
implicit none
integer, parameter :: dp = kind(1.0d0)
contains
function gf2_probability(n) result(prob)
integer, intent(in) :: n
real(kind=dp) :: prob
integer :: i
prob = 1.0_dp
do i = 1, n
   prob = prob * (1.0_dp - 1.0_dp / 2.0_dp**i)
end do
end function gf2_probability
end module m
program main
use m
implicit none
print "(f12.6)", gf2_probability(8)
end program main
""",
        encoding="utf-8",
    )

    normal = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert normal.returncode == 0, normal.stderr
    assert fast.returncode == 0, fast.stderr
    assert normal.stdout.strip() == "0.289919"
    assert fast.stdout == normal.stdout


def test_fast_is_invertible_real_specialization_matches_interpreter(tmp_path):
    source = tmp_path / "xfast_is_invertible_real.f90"
    source.write_text(
        """
module m
implicit none
integer, parameter :: dp = kind(1.0d0)
contains
function is_invertible_real(a_in) result(ok)
real(kind=dp), intent(in) :: a_in(:,:)
logical :: ok
real(kind=dp), allocatable :: a(:,:)
real(kind=dp) :: temp(size(a_in,2))
real(kind=dp) :: factor, pivot_abs, best_abs
integer :: n, i, j, k, pivot_row
real(kind=dp), parameter :: tol = 1.0d-10
n = size(a_in, 1)
allocate(a(n, n))
a = a_in
ok = .true.
do k = 1, n
   pivot_row = k
   best_abs = abs(a(k, k))
   do i = k + 1, n
      pivot_abs = abs(a(i, k))
      if (pivot_abs > best_abs) then
         best_abs = pivot_abs
         pivot_row = i
      end if
   end do
   if (best_abs <= tol) then
      ok = .false.
      return
   end if
   if (pivot_row /= k) then
      temp = a(k, :)
      a(k, :) = a(pivot_row, :)
      a(pivot_row, :) = temp
   end if
   do i = k + 1, n
      factor = a(i, k) / a(k, k)
      a(i, k) = 0.0_dp
      do j = k + 1, n
         a(i, j) = a(i, j) - factor * a(k, j)
      end do
   end do
end do
end function is_invertible_real
end module m
program main
use m
implicit none
real(kind=dp) :: a(2,2), b(2,2)
a = reshape([1.0_dp, 0.0_dp, 0.0_dp, 1.0_dp], shape(a))
b = reshape([1.0_dp, 2.0_dp, 2.0_dp, 4.0_dp], shape(b))
print *, is_invertible_real(a), is_invertible_real(b)
end program main
""",
        encoding="utf-8",
    )

    normal = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert normal.returncode == 0, normal.stderr
    assert fast.returncode == 0, fast.stderr
    assert normal.stdout.split() == ["T", "F"]
    assert fast.stdout == normal.stdout


def test_ofort_la_mod_is_invertible(tmp_path):
    source = tmp_path / "xofort_la_is_invertible.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: is_invertible
implicit none
real(8) :: a(2,2), b(2,2), c(2,3)
a = reshape([1.0d0, 0.0d0, 0.0d0, 1.0d0], shape(a))
b = reshape([1.0d0, 2.0d0, 2.0d0, 4.0d0], shape(b))
c = 0.0d0
print *, is_invertible(a), is_invertible(b), is_invertible(c)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert fast.returncode == 0, fast.stderr
    assert result.stdout.split() == ["T", "F", "F"]
    assert fast.stdout == result.stdout


def test_ofort_la_mod_det_and_stdlib_linalg_det(tmp_path):
    source = tmp_path / "xofort_la_det.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: det
use stdlib_linalg, only: std_det => det
implicit none
real(8) :: a(2,2), b(2,2)
complex(8) :: c(2,2)
a = reshape([1.0d0, 2.0d0, 3.0d0, 4.0d0], shape(a))
b = reshape([1.0d0, 2.0d0, 2.0d0, 4.0d0], shape(b))
c(1,1) = (1.0d0, 2.0d0)
c(2,1) = (3.0d0, 0.0d0)
c(1,2) = (0.0d0, 1.0d0)
c(2,2) = (4.0d0, -1.0d0)
print "(f8.3,1x,f8.3,1x,f8.3)", det(a), det(b), std_det(a)
print "(f8.3,1x,f8.3,1x,f8.3,1x,f8.3)", real(det(c)), aimag(det(c)), real(std_det(c)), aimag(std_det(c))
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert fast.returncode == 0, fast.stderr
    assert result.stdout.split() == ["-2.000", "0.000", "-2.000", "6.000", "4.000", "6.000", "4.000"]
    assert fast.stdout == result.stdout


def test_ofort_la_mod_matlab_style_functions(tmp_path):
    source = tmp_path / "xofort_la_matlab.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: norm, triu, tril, kron, solve, mldivide, inv, rank, chol
use stdlib_linalg, only: std_norm => norm, std_inv => inv, std_rank => rank
implicit none
real(8) :: a(2,2), b(2,1), v(2), rdef(2,2)
a = reshape([4.0d0, 2.0d0, 2.0d0, 3.0d0], shape(a))
b = reshape([10.0d0, 20.0d0], shape(b))
v = [1.0d0, 1.0d0]
rdef = reshape([1.0d0, 2.0d0, 2.0d0, 4.0d0], shape(rdef))
print *, norm([3.0d0, 4.0d0]), norm(a), std_norm([3.0d0, 4.0d0])
print *, triu(a)
print *, tril(a)
print *, kron(a, b)
print *, solve(a, v)
print *, mldivide(a, v)
print *, inv(a)
print *, rank(rdef), std_rank(rdef)
print *, chol(a)
print *, std_inv(a)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:3] == pytest.approx([5.0, 33.0 ** 0.5, 5.0])
    assert vals[3:7] == pytest.approx([4.0, 0.0, 2.0, 3.0])
    assert vals[7:11] == pytest.approx([4.0, 2.0, 0.0, 3.0])
    assert vals[11:19] == pytest.approx([40.0, 80.0, 20.0, 40.0, 20.0, 40.0, 30.0, 60.0])
    assert vals[19:21] == pytest.approx([0.125, 0.25])
    assert vals[21:23] == pytest.approx([0.125, 0.25])
    assert vals[23:27] == pytest.approx([0.375, -0.25, -0.25, 0.5])
    assert vals[27:29] == pytest.approx([1.0, 1.0])
    assert vals[29:33] == pytest.approx([2.0, 0.0, 1.0, 2.0 ** 0.5])
    assert vals[33:37] == pytest.approx([0.375, -0.25, -0.25, 0.5])


def test_ofort_la_mod_eig_svd_qr_lu_pinv_cond(tmp_path):
    source = tmp_path / "xofort_la_more_matlab.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: eig, svd, qr, lu, pinv, cond
use stdlib_linalg, only: std_eig => eig, std_svd => svd, std_cond => cond
implicit none
real(8) :: a(2,2), b(3,2), qra(3,2), wide(2,3)
a = reshape([2.0d0, 0.0d0, 0.0d0, 3.0d0], shape(a))
b = reshape([1.0d0, 0.0d0, 0.0d0, 0.0d0, 2.0d0, 0.0d0], shape(b))
qra = reshape([1.0d0, 0.0d0, 0.0d0, 1.0d0, 1.0d0, 0.0d0], shape(qra))
wide = reshape([1.0d0, 0.0d0, 0.0d0, 1.0d0, 0.0d0, 0.0d0], shape(wide))
print *, eig(a)
print *, std_eig(a)
print *, svd(b)
print *, std_svd(b)
print *, qr(qra)
print *, lu(a)
print *, pinv(b)
print *, pinv(wide)
print *, cond(a), std_cond(a)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:2] == pytest.approx([3.0, 2.0])
    assert vals[2:4] == pytest.approx([3.0, 2.0])
    assert vals[4:6] == pytest.approx([2.0, 1.0])
    assert vals[6:8] == pytest.approx([2.0, 1.0])
    assert vals[8:12] == pytest.approx([1.0, 0.0, 1.0, 1.0])
    assert vals[12:16] == pytest.approx([2.0, 0.0, 0.0, 3.0])
    assert vals[16:22] == pytest.approx([1.0, 0.0, 0.0, 0.5, 0.0, 0.0])
    assert vals[22:28] == pytest.approx([1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    assert vals[28:30] == pytest.approx([1.5, 1.5])


def test_ofort_sorting_mod_initial_functions(tmp_path):
    source = tmp_path / "xofort_sorting_mod.f90"
    source.write_text(
        """
program main
use ofort_sorting_mod, only: sorted, sort, sort_index, is_sorted, rank_order, unique
implicit none
integer :: i(5)
real(8) :: x(5)
character(len=3) :: s(4)
i = [3, 1, 2, 1, 3]
x = [3.0d0, 1.0d0, 2.0d0, 1.0d0, 3.0d0]
s = ["bb ", "a  ", "ccc", "bb "]
print *, sorted(i)
print *, sorted(x, reverse=.true.)
print *, sort_index(i)
print *, sort_index(i, reverse=.true.)
print *, is_sorted(sorted(i)), is_sorted(i), is_sorted(sorted(i, reverse=.true.), reverse=.true.)
print *, rank_order(i)
print *, unique(i)
print *, sorted(s)
print *, unique(s)
call sort(i)
call sort(x, reverse=.true.)
print *, i
print *, x
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    tokens = result.stdout.split()
    bools = [x for x in tokens if x in ("T", "F")]
    values = [x for x in tokens if x not in ("T", "F")]
    nums = [float(x) for x in values if x not in ("a", "bb", "ccc")]
    chars = [x for x in values if x in ("a", "bb", "ccc")]
    assert nums[0:5] == pytest.approx([1, 1, 2, 3, 3])
    assert nums[5:10] == pytest.approx([3, 3, 2, 1, 1])
    assert nums[10:15] == pytest.approx([2, 4, 3, 1, 5])
    assert nums[15:20] == pytest.approx([1, 5, 3, 2, 4])
    assert bools == ["T", "F", "T"]
    assert nums[20:25] == pytest.approx([4, 1, 3, 2, 5])
    assert nums[25:28] == pytest.approx([1, 2, 3])
    assert nums[28:33] == pytest.approx([1, 1, 2, 3, 3])
    assert nums[33:38] == pytest.approx([3, 3, 2, 1, 1])
    assert chars == ["a", "bb", "bb", "ccc", "a", "bb", "ccc"]


def test_warn_unused_respects_suppress_warnings(tmp_path):
    source = tmp_path / "xwarn_unused_suppressed.f90"
    source.write_text(
        """
program main
implicit none
integer :: used, assigned_only
used = 1
assigned_only = 2
print *, used
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "-w", "--warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1"]
    assert result.stderr == ""


def test_no_warn_unused_disables_default_unused_warning(tmp_path):
    source = tmp_path / "xwarn_unused_disabled.f90"
    source.write_text(
        """
program main
implicit none
integer :: used, assigned_only
used = 1
assigned_only = 2
print *, used
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1"]
    assert result.stderr == ""


def test_intrinsic_shadow_warning_and_option(tmp_path):
    source = tmp_path / "xshadow_intrinsic.f90"
    source.write_text(
        """
module m
implicit none
interface rank
   module procedure rank_real
end interface rank
contains
function rank_real(x) result(r)
real, intent(in) :: x(:)
integer :: r(size(x))
integer :: i, n, size
size = 1
n = ubound(x, 1)
r = [(i, i = 1, n)]
end function rank_real
end module m
program main
use m
implicit none
integer :: sum
sum = 3
print *, sum, rank([1.0, 2.0])
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["3", "1", "2"]
    assert "warning: generic interface 'rank' shadows intrinsic procedure RANK" in result.stderr
    assert "warning: variable 'size' shadows intrinsic procedure SIZE" in result.stderr
    assert "warning: variable 'sum' shadows intrinsic procedure SUM" in result.stderr

    quiet_result = subprocess.run(
        [str(OFORT), "--no-warn-unused", "--no-warn-intrinsic-shadow", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert quiet_result.returncode == 0, quiet_result.stderr
    assert quiet_result.stdout.split() == ["3", "1", "2"]
    assert "shadows intrinsic procedure" not in quiet_result.stderr


def test_repl_run_warns_about_unused_variables(tmp_path):
    result = subprocess.run(
        [str(OFORT), "--repl", "--nologo", "--prompt", ""],
        cwd=tmp_path,
        input=(
            "program main\n"
            "implicit none\n"
            "integer :: used, unused\n"
            "used = 1\n"
            "unused = 2\n"
            "print *, used\n"
            "end program main\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: variable 'unused' declared but never used" in result.stderr
    assert result.stdout.split() == ["1"]


def test_repl_save_warns_about_unused_variables(tmp_path):
    result = subprocess.run(
        [str(OFORT), "--repl", "--nologo", "--prompt", ""],
        cwd=tmp_path,
        input=(
            "integer :: used, unused\n"
            "used = 1\n"
            "unused = 2\n"
            ".save saved.f90\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: variable 'unused' declared but never used" in result.stderr
    assert "\nSaved saved.f90\n" in result.stdout
    assert (tmp_path / "saved.f90").exists()


def test_uninitialized_variable_read_is_rejected_by_default(tmp_path):
    source = tmp_path / "xundef.f90"
    source.write_text(
        """
implicit none
integer :: i
print *, i
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Variable 'i' is used before it is set" in result.stderr
    assert "line 4: print *, i" in result.stderr

    permissive_result = subprocess.run(
        [str(OFORT), "--no-check-uninitialized", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert permissive_result.returncode == 0, permissive_result.stderr
    assert permissive_result.stdout.split() == ["0"]

    synonym_result = subprocess.run(
        [str(OFORT), "--check-uninit", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert synonym_result.returncode != 0
    assert "Variable 'i' is used before it is set" in synonym_result.stderr


def test_unassigned_intent_out_dummy_leaves_actual_uninitialized(tmp_path):
    source = tmp_path / "xintent_out_unassigned.f90"
    source.write_text(
        """
module m
implicit none
contains
subroutine set_value(flag, x)
logical, intent(in) :: flag
integer, intent(out) :: x
if (flag) then
   x = 1
end if
end subroutine set_value
end module m

program main
use m
implicit none
integer :: i
call set_value(.false., i)
print *, i
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "warning: INTENT(OUT) argument 'x' of procedure 'set_value' may be returned uninitialized" in result.stderr
    assert "Variable 'i' is used before it is set" in result.stderr
    assert "line 19: print *, i" in result.stderr

    permissive_result = subprocess.run(
        [str(OFORT), "--no-check-uninitialized", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert permissive_result.returncode == 0, permissive_result.stderr
    assert permissive_result.stdout.split() == ["0"]
    assert "warning: INTENT(OUT) argument 'x' of procedure 'set_value' may be returned uninitialized" in permissive_result.stderr


def test_named_intent_out_actual_is_not_read_before_call(tmp_path):
    source = tmp_path / "xnamed_intent_out_uninit.f90"
    source.write_text(
        """
module m
implicit none
contains
subroutine set_status(x, ierr)
integer, intent(in) :: x
integer, intent(out), optional :: ierr
if (present(ierr)) ierr = x + 1
end subroutine set_status
end module m

program main
use m
implicit none
integer :: stat
call set_status(4, ierr=stat)
print *, stat
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["5"]


def test_function_keyword_argument_can_be_type_keyword(tmp_path):
    source = tmp_path / "xnamed_function_type_arg.f90"
    source.write_text(
        """
module m
implicit none
contains
function f(x, type) result(y)
integer, intent(in) :: x, type
integer :: y
y = x + type
end function f
end module m

program main
use m
implicit none
print *, f(4, type=3)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["7"]


def test_unallocated_allocatable_actual_status_is_defined(tmp_path):
    source = tmp_path / "xallocatable_status_defined.f90"
    source.write_text(
        """
module m
implicit none
contains
subroutine check_size(a)
integer, allocatable, intent(in) :: a(:)
print *, size(a)
end subroutine check_size
end module m

program main
use m
implicit none
integer, allocatable :: a(:)
call check_size(a)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0"]


def test_unallocated_allocatable_array_assignment_auto_allocates_with_shadowed_name(tmp_path):
    source = tmp_path / "xalloc_assign_shadow.f90"
    source.write_text(
        """
module m
implicit none
real, parameter :: pi = 3.14
contains
subroutine s()
real, allocatable :: pi(:)
pi = [1.0, 2.0]
print *, size(pi), pi
end subroutine s
end module m

program main
use m
implicit none
call s()
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "1.0", "2.0"]


def test_scalar_logical_and_or_short_circuit(tmp_path):
    source = tmp_path / "xlogical_short_circuit.f90"
    source.write_text(
        """
integer :: x(2)
x = [10, 20]
if (0 >= 1 .and. x(0) > 0) print *, "bad"
if (1 == 1 .or. x(0) > 0) print *, "ok"
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["ok"]


def test_unguarded_optional_dummy_use_warns(tmp_path):
    source = tmp_path / "xoptional_unguarded.f90"
    source.write_text(
        """
module m
implicit none
contains
subroutine unsafe(i)
integer, intent(in), optional :: i
print *, "in unsafe, i =", i
end subroutine unsafe

subroutine guarded(i)
integer, intent(in), optional :: i
if (present(i)) print *, i
end subroutine guarded

subroutine early_return_guard(i)
integer, intent(in), optional :: i
if (.not. present(i)) return
print *, i
end subroutine early_return_guard
end module m

program main
use m
implicit none
call unsafe(3)
call guarded()
call early_return_guard()
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["in", "unsafe,", "i", "=", "3"]
    assert "warning: OPTIONAL argument 'i' of procedure 'unsafe' may be used when not present" in result.stderr
    assert "guarded" not in result.stderr
    assert "early_return_guard" not in result.stderr

    quiet_result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert quiet_result.returncode == 0, quiet_result.stderr
    assert quiet_result.stderr == ""

    werror_result = subprocess.run(
        [str(OFORT), "-Werror", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert werror_result.returncode != 0
    assert "warning: OPTIONAL argument 'i' of procedure 'unsafe' may be used when not present" in werror_result.stderr
    assert "warnings treated as errors" in werror_result.stderr

    long_werror_result = subprocess.run(
        [str(OFORT), "--warn-error", "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert long_werror_result.returncode == 0, long_werror_result.stderr
    assert long_werror_result.stderr == ""


def test_init_int_and_init_real_options_set_debug_defaults(tmp_path):
    source = tmp_path / "xinit_debug.f90"
    source.write_text(
        """
implicit none
integer :: i, a(2)
real :: x, r(2)
double precision :: d
print *, i, a
print *, x, r
print *, d
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--init-int", "-999", "--init-real", "-1.5", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["-999", "-999", "-999", "-1.5", "-1.5", "-1.5", "-1.5"]


def test_init_real_accepts_nan(tmp_path):
    source = tmp_path / "xinit_nan.f90"
    source.write_text(
        """
implicit none
real :: x
double precision :: d
print *, x /= x, d /= d
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--init-real", "nan", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["T", "T"]


def test_init_char_option_sets_debug_defaults(tmp_path):
    source = tmp_path / "xinit_char.f90"
    source.write_text(
        """
implicit none
character(len=5) :: s
character(len=3) :: a(2)
character(len=4) :: explicit = "ok"
print *, "[" // s // "]"
print *, "[" // a(1) // "]", "[" // a(2) // "]"
print *, "[" // trim(explicit) // "]"
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--init-char", "?", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["[?????]", "[???]", "[???]", "[ok]"]


def test_pure_function_requires_result_type_and_intent_in_dummy(tmp_path):
    source = tmp_path / "xcheck_pure_func.f90"
    source.write_text(
        """
program main
implicit none
print *, f(3)
contains
pure function f(i)
integer :: i
f = 2*i
end function f
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Function result 'f' in PURE function 'f' has no declared type" in result.stderr
    assert "Argument 'i' of PURE function 'f' must be INTENT(IN) or VALUE" in result.stderr


def test_pure_function_rejects_impure_function_reference(tmp_path):
    source = tmp_path / "xcheck_pure_func_call.f90"
    source.write_text(
        """
program main
implicit none
print *, f(3)
contains
pure integer function f(i)
integer, intent(in) :: i
f = g(i)
end function f

integer function g(i)
integer, intent(in) :: i
g = 2*i
end function g
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Reference to impure function 'g'" in result.stderr
    assert "within PURE procedure" in result.stderr


def test_namelist_read_write_roundtrip(tmp_path):
    source = tmp_path / "xnamelist.f90"
    source.write_text(
        """
program test_namelist
   implicit none

   integer, parameter :: dp = kind(1.0d0)
   integer :: i, n
   real(kind=dp) :: x, y
   logical :: flag
   character(len=20) :: title
   integer :: a(3)
   real(kind=dp) :: b(2, 2)

   namelist /params/ n, x, y, flag, title, a, b

   n = 0
   x = 0.0_dp
   y = 0.0_dp
   flag = .false.
   title = "unset"
   a = 0
   b = 0.0_dp

   write(*, nml=params)

   open(unit=10, file="test_namelist.in", status="replace", action="write")
   write(10, '(a)') "&params"
   write(10, '(a)') " n = 5,"
   write(10, '(a)') " x = 1.25,"
   write(10, '(a)') " y = -3.5,"
   write(10, '(a)') " flag = .true.,"
   write(10, '(a)') " title = 'compiler test',"
   write(10, '(a)') " a = 10, 20, 30,"
   write(10, '(a)') " b = 1.0, 2.0, 3.0, 4.0"
   write(10, '(a)') "/"
   close(10)

   open(unit=11, file="test_namelist.in", status="old", action="read")
   read(11, nml=params)
   close(11)

   print *, "values after reading namelist"
   print *, "n     =", n
   print *, "x     =", x
   print *, "y     =", y
   print *, "flag  =", flag
   print *, "title =", trim(title)
   print *, "a     =", a
   print *, "b     ="
   do i = 1, 2
      print *, b(i, :)
   end do

   write(*, nml=params)
end program test_namelist
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    out = result.stdout
    assert out.count("&params") == 2
    assert "values after reading namelist" in out
    assert "n     = 5" in out
    assert "x     = 1.25" in out
    assert "y     = -3.5" in out
    assert "flag  = T" in out
    assert "title = compiler test" in out
    assert "a     = 10 20 30" in out
    assert "1.0 3.0" in out
    assert "2.0 4.0" in out
    assert " title = \"compiler test       \"," in out


def test_namelist_group_name_imported_from_module(tmp_path):
    source = tmp_path / "xnamelist_module.f90"
    source.write_text(
        """
module mod0
implicit none
real :: a, b
namelist /aa/ a, b
end module mod0

use mod0
implicit none
a = 1.0
b = 2.0
write(6, aa)
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert "&aa" in result.stdout
    assert " a = 1" in result.stdout
    assert " b = 2" in result.stdout


def test_namelist_group_name_use_rename(tmp_path):
    source = tmp_path / "xnamelist_rename.f90"
    source.write_text(
        """
module mod0
implicit none
real :: a, b
namelist /aa/ a, b
end module mod0

module mod1
use mod0, xxx => aa
end module mod1

use mod1
implicit none
a = 3.0
b = 4.0
write(6, xxx)
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert "&xxx" in result.stdout
    assert " a = 3" in result.stdout
    assert " b = 4" in result.stdout


def test_extends_inherits_fields_and_dispatches_dynamically(tmp_path):
    source = tmp_path / "xextends_min.f90"
    source.write_text(
        """
module shape_mod
implicit none

type :: shape
   character(len=20) :: name = "shape"
contains
   procedure :: describe => describe_shape
   procedure :: area => area_shape
end type shape

type, extends(shape) :: circle
   real :: radius = 0.0
contains
   procedure :: describe => describe_circle
   procedure :: area => area_circle
end type circle

contains

subroutine describe_shape(this)
   class(shape), intent(in) :: this
   print *, "shape", trim(this%name)
end subroutine describe_shape

function area_shape(this) result(y)
   class(shape), intent(in) :: this
   real :: y
   y = 0.0
end function area_shape

subroutine describe_circle(this)
   class(circle), intent(in) :: this
   print *, "circle", trim(this%name), this%radius
end subroutine describe_circle

function area_circle(this) result(y)
   class(circle), intent(in) :: this
   real :: y
   y = this%radius * this%radius
end function area_circle

subroutine print_shape_info(s)
   class(shape), intent(in) :: s
   call s%describe()
   print *, "area", s%area()
end subroutine print_shape_info

end module shape_mod

program main
use shape_mod
implicit none

type(shape) :: s
type(circle) :: c

s%name = "plain"
c%name = "unit"
c%radius = 2.0

call s%describe()
print *, s%area()
call c%describe()
print *, c%area()
call print_shape_info(s)
call print_shape_info(c)
end program main
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == [
        "shape", "plain",
        "0.0",
        "circle", "unit", "2.0",
        "4.0",
        "shape", "plain",
        "area", "0.0",
        "circle", "unit", "2.0",
        "area", "4.0",
    ]


def test_check_registers_bare_main_contained_functions(tmp_path):
    source = tmp_path / "contained_function_check.f90"
    source.write_text(
        """
implicit none
integer :: n
n = f(2)
contains
integer function f(x)
   integer, intent(in) :: x
   f = x
end function
end
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "ofort check passed\n"
    assert result.stderr == ""


def test_recursive_allocatable_derived_component_is_unallocated_by_default(tmp_path):
    source = tmp_path / "recursive_alloc_component.f90"
    source.write_text(
        """
implicit none
type node
   real :: x = 1.0
   type(node), allocatable :: next
end type
type wrapper
   type(node) :: first
end type
type(wrapper) :: w
print *, w%first%x
end
""",
        encoding="utf-8",
    )

    check = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )
    run = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert check.returncode == 0, check.stdout + check.stderr
    assert check.stdout == "ofort check passed\n"
    assert check.stderr == ""
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.strip() == "1.0"
    assert run.stderr == ""


@pytest.mark.parametrize("source", case_files(), ids=lambda p: p.stem)
def test_case_stdout(source):
    expected = source.with_suffix(".out").read_text(encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", "--no-warn-intrinsic-shadow", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == expected


def test_g0_formats_real_expressions_without_one_digit_rounding(tmp_path):
    source = tmp_path / "xg0_real_expr.f90"
    source.write_text(
        "use, intrinsic :: iso_fortran_env, only: real64\n"
        "implicit none\n"
        "integer, parameter :: dp = real64\n"
        "real(kind=dp) :: x(4)\n"
        "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
        "write(*,\"(g0)\") sum(x) / size(x)\n"
        "write(*,\"(g0)\") sqrt(sum((x - sum(x) / size(x))**2) / 3.0_dp)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(2.5)
    assert float(lines[1]) == pytest.approx(1.2909944487358056)


def test_implicit_integer_real_assignment_warns_but_runs():
    source = CASES / "ximplicit_typing_ranges.f90"
    expected = source.with_suffix(".out").read_text(encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
    assert "warning: assigning REAL to INTEGER variable 'i' truncates toward zero" in result.stderr
    assert "line 3: i = 2.8" in result.stderr


def test_entry_statement_is_reported_obsolescent():
    source = CASES / "xentry_obsolescent.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr


def test_alternate_return_is_reported_obsolescent():
    source = CASES / "xalternate_return_obsolescent.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr


def test_alternate_return_dummy_is_reported_obsolescent():
    source = CASES / "xalternate_return_dummy_obsolescent.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr


@pytest.mark.parametrize(
    ("case_name", "arg_name"),
    [
        ("xoptional_absent_scalar_use", "i"),
        ("xoptional_absent_allocated_use", "a"),
        ("xoptional_absent_associated_use", "p"),
        ("xoptional_absent_component_use", "arg"),
    ],
)
def test_absent_optional_dummy_use_is_error(case_name, arg_name):
    source = CASES / f"{case_name}.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert f"Optional dummy argument '{arg_name}' is not present" in result.stderr


def test_implicit_derived_type_warns_but_runs():
    source = CASES / "ximplicit_derived_type.f90"
    expected = source.with_suffix(".out").read_text(encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
    assert "warning: derived-type implicit typing is legal but discouraged; prefer explicit declarations" in result.stderr
    assert "line 4: implicit type(t) (a-b)" in result.stderr


def test_allocate_rejects_already_allocated_variable():
    source = CASES / "xallocate_already_allocated.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr
    assert "line 17: allocate (dates(4))" in result.stderr


def test_parser_expected_token_errors_are_readable(tmp_path):
    source = tmp_path / "xbad_syntax.f90"
    source.write_text("integer : i\nend\n", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Expected token type" not in result.stderr
    assert "Syntax error at line 1: expected identifier but found ':'" in result.stderr
    assert "line 1: integer : i" in result.stderr


def test_check_reports_undeclared_identifier_with_implicit_none(tmp_path):
    source = tmp_path / "xcheck_implicit_none.f90"
    source.write_text(
        "program main\n"
        "  implicit none\n"
        "  integer :: n\n"
        "  n = 2**5\n"
        "  print *, m\n"
        "end program main\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Undefined variable 'm' at line 5" in result.stderr
    assert "line 5:   print *, m" in result.stderr


def test_trace_assign_reports_assignment_values(tmp_path):
    source = tmp_path / "xtrace_assign.f90"
    source.write_text(
        "integer :: x\n"
        "x = 1\n"
        "x = x + 2\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), "--trace-assign", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "3\n"
    assert result.stderr == "1\n3\n"


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


def test_cpu_time_runs_and_reports_elapsed_time():
    source = CASES / "xcpu_time.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "cpu_time returns CPU time in seconds.",
        "",
    ]
    assert re.match(r"^result s = \d+(?:\.\d+)?(?:e[+-]?\d+)?$", lines[2])
    match = re.match(r"^CPU time = ([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?) seconds$", lines[3])
    assert match
    assert float(match.group(1)) >= 0.0


def test_date_and_time_reports_clock_fields():
    source = CASES / "xdate_and_time.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert "date only:" in lines
    assert "time only:" in lines
    assert "zone only:" in lines
    assert "values only:" in lines
    assert "all arguments:" in lines
    date_match = re.search(r"(?m)^date =  (\d{8})$", result.stdout)
    time_match = re.search(r"(?m)^time =  (\d{6}\.\d{3})$", result.stdout)
    zone_match = re.search(r"(?m)^zone =  ([+-]\d{4})$", result.stdout)
    values_match = re.search(
        r"(?m)^values =  (\d{4}) (\d{1,2}) (\d{1,2}) ([+-]?\d+) "
        r"(\d{1,2}) (\d{1,2}) (\d{1,2}) (\d{1,3})$",
        result.stdout,
    )
    formatted_match = re.search(
        r"(?m)^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3}) ([+-]\d{4})$",
        result.stdout,
    )
    assert date_match
    assert time_match
    assert zone_match
    assert values_match
    assert formatted_match
    year, month, day, offset, hour, minute, second, millisecond = values_match.groups()
    assert date_match.group(1) == f"{year}{int(month):02d}{int(day):02d}"
    assert time_match.group(1) == f"{int(hour):02d}{int(minute):02d}{int(second):02d}.{int(millisecond):03d}"
    assert zone_match.group(1) == formatted_match.group(8)
    assert formatted_match.groups()[:7] == (
        year,
        f"{int(month):02d}",
        f"{int(day):02d}",
        f"{int(hour):02d}",
        f"{int(minute):02d}",
        f"{int(second):02d}",
        f"{int(millisecond):03d}",
    )
    assert -1440 <= int(offset) <= 1440


def test_fast_date_and_time_values_uses_packed_integer_array(tmp_path):
    source = tmp_path / "xfast_date_values.f90"
    source.write_text(
        "integer :: values(8)\n"
        "call date_and_time(values=values)\n"
        "print *, values(1) > 2000, values(2) >= 1, values(8) >= 0\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["T", "T", "T"]


def test_transfer_reinterprets_basic_values():
    source = CASES / "xtransfer.f90"
    result = subprocess.run(
        [str(OFORT), "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "integer to real:" in result.stdout
    assert "real to integer:" in result.stdout
    assert "character to integer:" in result.stdout
    assert "array result using size argument:" in result.stdout

    int_to_real = re.findall(r"ia\(i\) = (\d+)  transfer -> real = ([0-9.e+-]+)", result.stdout)
    assert [int(i) for i, _ in int_to_real] == [1, 2, 3, 4]
    assert [pytest.approx(float(x), rel=1e-6) for _, x in int_to_real] == [
        1.401298e-45,
        2.802597e-45,
        4.203895e-45,
        5.605194e-45,
    ]

    real_to_int = re.findall(r"ra\(i\) = ([0-9.]+)  transfer -> integer = (\d+)", result.stdout)
    assert [(int(float(r)), int(i)) for r, i in real_to_int] == [
        (1, 1065353216),
        (2, 1073741824),
        (3, 1077936128),
        (4, 1082130432),
    ]

    assert "s = ABCD  transfer(s,0) = 1145258561" in result.stdout
    assert "transfer(ia, 0.0, size=2) = 1.401298e-45 2.802597e-45" in result.stdout
    assert "transfer(ia, 0.0, size=1) = 1.401298e-45" in result.stdout


def test_formatted_print_expands_random_array():
    source = CASES / "xrandom_print_array.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parts = result.stdout.split()
    assert len(parts) == 2
    assert all(0.0 <= float(part) < 1.0 for part in parts)


def test_implicit_none_rejects_undeclared_variable():
    source = CASES / "ximplicit_none.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'i' has no implicit type" in result.stderr
    assert "line 2: i = 2" in result.stderr


def test_implicit_typing_is_rejected_by_default():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'i' has no implicit type" in result.stderr
    assert "--implicit-typing" in result.stderr


def test_no_implicit_typing_option_rejects_undeclared_variable():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), "--no-implicit-typing", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'i' has no implicit type" in result.stderr
    assert "--implicit-typing" in result.stderr


def test_implicit_typing_option_allows_legacy_default():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), "--implicit-typing", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2"]
    assert result.stderr == ""


def test_command_arguments_from_file_mode(tmp_path):
    source = tmp_path / "xargs.f90"
    source.write_text(
        "program xargs\n"
        "implicit none\n"
        "integer :: n, length, status\n"
        "character(len=8) :: arg\n"
        "n = command_argument_count()\n"
        "print *, n\n"
        "call get_command_argument(1, arg, length, status)\n"
        "print *, trim(arg), length, status\n"
        "call get_command_argument(2, arg, length, status)\n"
        "print *, trim(arg), length, status\n"
        "end program xargs\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "--", "alpha", "longer_than_8"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "2",
        "alpha 5 0",
        "longer_t 13 -1",
    ]


def test_get_command_argument_missing_value_is_blank(tmp_path):
    source = tmp_path / "xmissing_arg.f90"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "character(len=10) :: arg\n"
        "integer :: n, stat\n"
        "arg = 'unchanged'\n"
        "call get_command_argument(1, value=arg)\n"
        "print *, '[' // arg // ']'\n"
        "call get_command_argument(1, value=arg, length=n, status=stat)\n"
        "print *, '[' // arg // ']', n, stat\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == ["[          ]", "[          ] 0 1"]


def test_getarg_extension_from_file_mode(tmp_path):
    source = tmp_path / "xgetarg.f90"
    source.write_text(
        "program xgetarg\n"
        "implicit none\n"
        "character(len=8) :: arg\n"
        "call getarg(1, arg)\n"
        "print *, trim(arg)\n"
        "end program xgetarg\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "--", "alpha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alpha"
    assert "warning: nonstandard GETARG extension; prefer GET_COMMAND_ARGUMENT" in result.stderr


def test_w_option_suppresses_getarg_warning(tmp_path):
    source = tmp_path / "xgetarg.f90"
    source.write_text(
        "program xgetarg\n"
        "implicit none\n"
        "character(len=8) :: arg\n"
        "call getarg(1, arg)\n"
        "print *, trim(arg)\n"
        "end program xgetarg\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "-w", str(source), "--", "alpha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alpha"
    assert result.stderr == ""


def test_multiple_source_files_are_concatenated(tmp_path):
    first = tmp_path / "part1.f90"
    second = tmp_path / "part2.f90"
    first.write_text(
        "program xmulti\n"
        "implicit none\n"
        "integer :: i\n"
        "i = 6\n",
        encoding="utf-8",
    )
    second.write_text(
        "print *, i * 7\n"
        "end program xmulti\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(first), str(second)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["42"]


def test_extensionless_source_argument_tries_f90(tmp_path):
    source = tmp_path / "xshortcut.f90"
    source.write_text(
        "program xshortcut\n"
        "  print *, 42\n"
        "end program xshortcut\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(tmp_path / "xshortcut")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "42\n"


def test_existing_extensionless_source_argument_wins_over_f90(tmp_path):
    source = tmp_path / "xshortcut"
    source_f90 = tmp_path / "xshortcut.f90"
    source.write_text(
        "program xshortcut\n"
        "  print *, 7\n"
        "end program xshortcut\n",
        encoding="utf-8",
    )
    source_f90.write_text(
        "program xshortcut\n"
        "  print *, 99\n"
        "end program xshortcut\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "7\n"


def test_manifest_source_files_are_concatenated(tmp_path):
    first = tmp_path / "part1.f90"
    second = tmp_path / "part2.f90"
    manifest = tmp_path / "files.txt"
    first.write_text(
        "program xmanifest\n"
        "implicit none\n"
        "integer :: i\n"
        "i = 7\n",
        encoding="utf-8",
    )
    second.write_text(
        "print *, i * 6\n"
        "end program xmanifest\n",
        encoding="utf-8",
    )
    manifest.write_text(
        "# relative paths are resolved from the manifest directory\n"
        "part1.f90\n"
        "\n"
        "! another comment\n"
        "part2.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), f"@{manifest}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["42"]


def test_manifest_each_mode_runs_files_separately(tmp_path):
    first = tmp_path / "a.f90"
    second = tmp_path / "b.f90"
    manifest = tmp_path / "files.txt"
    first.write_text("print *, 11\nend\n", encoding="utf-8")
    second.write_text("print *, 22\nend\n", encoding="utf-8")
    manifest.write_text("a.f90\nb.f90\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--each", f"@{manifest}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "a.f90" in result.stdout
    assert "b.f90" in result.stdout
    assert "11" in result.stdout.split()
    assert "22" in result.stdout.split()


def test_each_dep_manifest_runs_mains_with_separate_dependencies(tmp_path):
    first_main = tmp_path / "a.f90"
    second_main = tmp_path / "b.f90"
    first_mod = tmp_path / "first.f90"
    second_mod = tmp_path / "second.f90"
    manifest = tmp_path / "main_programs.txt"

    first_main.write_text(
        "program a\n"
        "use first\n"
        "print *, value()\n"
        "end program a\n",
        encoding="utf-8",
    )
    second_main.write_text(
        "program b\n"
        "use second\n"
        "print *, value()\n"
        "end program b\n",
        encoding="utf-8",
    )
    first_mod.write_text(
        "module first\n"
        "contains\n"
        "integer function value()\n"
        "value = 101\n"
        "end function value\n"
        "end module first\n",
        encoding="utf-8",
    )
    second_mod.write_text(
        "module second\n"
        "contains\n"
        "integer function value()\n"
        "value = 202\n"
        "end function value\n"
        "end module second\n",
        encoding="utf-8",
    )
    manifest.write_text("a.f90\nb.f90\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--each", "--dep", f"@{manifest}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "a.f90" in result.stdout
    assert "b.f90" in result.stdout
    assert "101" in result.stdout.split()
    assert "202" in result.stdout.split()
    assert "checked 2 files: 2 passed, 0 failed" in result.stdout


def test_manifest_errors_include_source_file_name(tmp_path):
    first = tmp_path / "part1.f90"
    second = tmp_path / "part2.f90"
    manifest = tmp_path / "files.txt"
    first.write_text(
        "program xmanifest_error\n"
        "implicit none\n",
        encoding="utf-8",
    )
    second.write_text(
        "print *, 1 .bad. 2\n"
        "end program xmanifest_error\n",
        encoding="utf-8",
    )
    manifest.write_text("part1.f90\npart2.f90\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), f"@{manifest}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert str(second) in result.stderr
    assert f"{second}:1:" in result.stderr
    assert "line 3:" in result.stderr


def test_private_module_names_are_not_imported(tmp_path):
    source = tmp_path / "xprivate_hidden.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: pi\n"
        "real :: pi = 3.14\n"
        "real :: hidden = 2.0\n"
        "end module m\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "print *, hidden\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Undefined variable 'hidden'" in result.stderr


def test_protected_module_variable_cannot_be_assigned_after_use(tmp_path):
    source = tmp_path / "xprotected_assign.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "real, protected :: pi = 3.14\n"
        "end module m\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "pi = 4.0\n"
        "print *, pi\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Cannot assign to PROTECTED variable 'pi'" in result.stderr


def test_recursive_io_is_diagnosed(tmp_path):
    source = tmp_path / "xrecursive_io.f90"
    source.write_text(
        "module m\n"
        "contains\n"
        "function f(x) result(y)\n"
        "real, intent(in) :: x\n"
        "real :: y\n"
        "print *, 'nested io'\n"
        "y = x\n"
        "end function f\n"
        "end module m\n"
        "program main\n"
        "use m\n"
        "print *, f(1.0)\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Recursive I/O not allowed" in result.stderr
    assert "line 6: print *, 'nested io'" in result.stderr


def test_save_warns_for_implicit_save_local():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert "warning: local variable 'mcall' has implicit SAVE due to initialization" in result.stderr
    assert "integer :: mcall = 0" in result.stderr
    assert "ncall" not in result.stderr


def test_w_option_suppresses_warnings():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_implicit_external_unit_warns(tmp_path):
    source = tmp_path / "ximplicit_unit.f90"
    source.write_text(
        "integer :: i, j\n"
        "write(12,*) 70, 80\n"
        "rewind 12\n"
        "read(12,*) i, j\n"
        "print *, i, j\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "70 80\n"
    assert "warning: implicit external unit 12 uses default file 'fort.12'; prefer OPEN with FILE=" in result.stderr
    assert (tmp_path / "fort.12").read_text(encoding="utf-8") == "70 80\n"


def test_w_option_suppresses_implicit_external_unit_warning(tmp_path):
    source = tmp_path / "ximplicit_unit.f90"
    source.write_text(
        "integer :: i, j\n"
        "write(12,*) 70, 80\n"
        "rewind 12\n"
        "read(12,*) i, j\n"
        "print *, i, j\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "70 80\n"
    assert result.stderr == ""


def test_input_unit_reads_from_stdin(tmp_path):
    source = CASES / "xinput_output_unit.f90"

    result = subprocess.run(
        [str(OFORT), str(source)],
        input="Alice\n33\n",
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")


def test_advance_no_prompt_before_read_star_stdin():
    source = CASES / "xadvance_no.f90"

    result = subprocess.run(
        [str(OFORT), str(source)],
        input="3 4\n",
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")


def test_fast_option_suppresses_warnings_and_preserves_output():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_real_star_8_extension_warns_and_runs(tmp_path):
    source = tmp_path / "xreal_star_8.f90"
    source.write_text(
        "real*8 :: x\n"
        "x = 1.25d0\n"
        "print *, kind(x), x\n"
        "end\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "8 1.25\n"
    assert "warning: nonstandard REAL*8 treated as REAL(KIND=8) extension" in result.stderr


def test_w_option_suppresses_real_star_8_warning(tmp_path):
    source = tmp_path / "xreal_star_8.f90"
    source.write_text(
        "real*8 :: x\n"
        "x = 1.25d0\n"
        "print *, kind(x), x\n"
        "end\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "8 1.25\n"
    assert result.stderr == ""


def test_write_extra_comma_warns_and_runs(tmp_path):
    source = tmp_path / "xwrite_comma.f90"
    source.write_text(
        'write (*,*), "hello"\n'
        "end\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello\n"
    assert "warning: nonstandard comma between WRITE control list and I/O list" in result.stderr


def test_write_extra_comma_rejected_by_f2023(tmp_path):
    source = tmp_path / "xwrite_comma.f90"
    source.write_text(
        'write (*,*), "hello"\n'
        "end\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), "--std=f2023", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "nonstandard comma between WRITE control list and I/O list is not allowed with --std=f2023" in result.stderr


def test_f2023_default_leading_zero_mode_suppresses_optional_zero(tmp_path):
    source = tmp_path / "xlz_default.f90"
    source.write_text(
        "implicit none\n"
        "print \"(*(1x,f0.3))\", [-0.125, 0.0, 0.125]\n"
        "end\n",
        encoding="utf-8",
    )

    legacy = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    strict = subprocess.run(
        [str(OFORT), "--std=f2023", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert legacy.returncode == 0, legacy.stderr
    assert strict.returncode == 0, strict.stderr
    assert legacy.stdout == " -0.125 0.000 0.125\n"
    assert strict.stdout == " -.125 .000 .125\n"


def test_fast_option_preserves_counted_do_loop_result():
    source = CASES / "xlarge_do_loop.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_initialized_arrays():
    source = CASES / "xarray_init.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_rank2_array_expressions():
    source = CASES / "xfast_rank2_array_expr.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_aliases_array_dummy_arguments():
    source = CASES / "xfast_array_dummy_alias.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_reuses_local_array_storage_safely():
    source = CASES / "xfast_local_array_reuse.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_nested_numeric_do_loops():
    source = CASES / "xfast_numeric_do_loop.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_array_random_number_and_sum(tmp_path):
    source = tmp_path / "xfast_array.f90"
    source.write_text(
        "integer, parameter :: n = 1000\n"
        "real :: x(n)\n"
        "call random_number(x)\n"
        "print *, sum(x) / size(x)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    mean = float(result.stdout.strip())
    assert 0.0 <= mean <= 1.0


def test_fast_random_number_advances_state(tmp_path):
    source = tmp_path / "xfast_random_state.f90"
    source.write_text(
        "real :: x\n"
        "call random_number(x)\n"
        "print *, x\n"
        "call random_number(x)\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    values = [float(line) for line in result.stdout.splitlines()]
    assert len(values) == 2
    assert all(0.0 <= value < 1.0 for value in values)
    assert values[0] != values[1]


def test_fast_packed_array_reads_default_numeric_element(tmp_path):
    source = tmp_path / "xfast_packed_default.f90"
    source.write_text(
        "real :: x(3)\n"
        "print *, kind(x(1)), x(1)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "4 0.0\n"


def test_fast_packed_array_power_can_be_summed(tmp_path):
    source = tmp_path / "xfast_packed_power_sum.f90"
    source.write_text(
        "real :: x(3)\n"
        "x(1) = 1.0\n"
        "x(2) = 2.0\n"
        "x(3) = 3.0\n"
        "print *, sum(x), sum(x**2)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "6.0 14.0\n"


def test_fast_packed_dot_product_matches_sum_product():
    source = CASES / "xfast_dot_product.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")


def test_fast_packed_array_intrinsics_use_packed_storage():
    source = CASES / "xfast_array_intrinsics_packed.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")


def test_fast_scalar_numeric_update(tmp_path):
    source = tmp_path / "xfast_scalar_update.f90"
    source.write_text(
        "real :: x, xsum\n"
        "integer :: i\n"
        "x = 0.25\n"
        "xsum = 0.0\n"
        "do i = 1, 4\n"
        "  xsum = xsum + x\n"
        "end do\n"
        "print *, xsum\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "1.0\n"


def test_fast_random_sum_loop_pattern(tmp_path):
    source = tmp_path / "xfast_random_sum_loop.f90"
    source.write_text(
        "integer, parameter :: n = 1000\n"
        "real :: x, xsum\n"
        "integer :: i\n"
        "xsum = 0.0\n"
        "do i = 1, n\n"
        "  call random_number(x)\n"
        "  xsum = xsum + x\n"
        "end do\n"
        "print *, i, xsum/n\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    fields = result.stdout.split()
    assert int(fields[0]) == 1001
    assert 0.0 <= float(fields[1]) < 1.0


def test_time_option_reports_execution_time_without_changing_stdout():
    source = CASES / "xtry.f90"
    result = subprocess.run(
        [str(OFORT), "--time", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert re.search(r"(?m)^time: \d+\.\d{6} s$", result.stderr)


def test_time_option_does_not_report_time_after_error(tmp_path):
    source = tmp_path / "ximplicit_none_time.f90"
    source.write_text(
        "implicit none\n"
        "integer :: i\n"
        "i = 2\n"
        "elapsed_s = i\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--time", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'elapsed_s' has no implicit type" in result.stderr
    assert not re.search(r"(?m)^time: \d+\.\d{6} s$", result.stderr)


def test_native_subroutine_can_call_precompiled_fortran(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_stats.f90"
    native_dll = tmp_path / "native_stats.dll"
    source = tmp_path / "xnative_stats.f90"
    native_source.write_text(
        'subroutine stats_c(nx, x, ny, y) bind(C, name="stats_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: nx\n"
        "  integer(c_int), intent(in) :: ny\n"
        "  real(c_double), intent(in) :: x(nx)\n"
        "  real(c_double), intent(out) :: y(ny)\n"
        "  y(1) = sum(x) / real(nx, c_double)\n"
        "  y(2) = sqrt(sum((x - y(1))**2) / real(nx - 1, c_double))\n"
        "end subroutine stats_c\n",
        encoding="utf-8",
    )
    source.write_text(
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(4), y(2)\n"
        "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
        "call stats(x, y)\n"
        "print *, y\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), "--native", f"stats={native_dll}:stats_c", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    fields = result.stdout.split()
    assert fields[0] == "2.5"
    assert abs(float(fields[1]) - 1.2909944487358056) < 1.0e-5


def test_native_subroutine_directive_can_call_precompiled_fortran(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_stats_directive.f90"
    native_dll = tmp_path / "native_stats_directive.dll"
    source = tmp_path / "xnative_stats_directive.f90"
    native_source.write_text(
        'subroutine stats_c(nx, x, ny, y) bind(C, name="stats_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: nx\n"
        "  integer(c_int), intent(in) :: ny\n"
        "  real(c_double), intent(in) :: x(nx)\n"
        "  real(c_double), intent(out) :: y(ny)\n"
        "  y(1) = sum(x) / real(nx, c_double)\n"
        "  y(2) = sqrt(sum((x - y(1))**2) / real(nx - 1, c_double))\n"
        "end subroutine stats_c\n",
        encoding="utf-8",
    )
    source.write_text(
        f"!$ofort native stats={native_dll}:stats_c\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(4), y(2)\n"
        "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
        "call stats(x, y)\n"
        "print *, y\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    fields = result.stdout.split()
    assert fields[0] == "2.5"
    assert abs(float(fields[1]) - 1.2909944487358056) < 1.0e-5


def test_native_function_directive_can_return_scalar(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_mean.f90"
    native_dll = tmp_path / "native_mean.dll"
    source = tmp_path / "xnative_mean.f90"
    native_source.write_text(
        'subroutine mean_c(nx, x, xmean) bind(C, name="mean_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: nx\n"
        "  real(c_double), intent(in) :: x(nx)\n"
        "  real(c_double), intent(out) :: xmean\n"
        "  xmean = sum(x) / real(nx, c_double)\n"
        "end subroutine mean_c\n",
        encoding="utf-8",
    )
    source.write_text(
        f"!$ofort native mean={native_dll}:mean_c,r8arr_r8\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(4), xmean\n"
        "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
        "xmean = mean(x)\n"
        "print *, xmean\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["2.5"]


def test_native_function_directive_can_use_two_arrays(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_dot.f90"
    native_dll = tmp_path / "native_dot.dll"
    source = tmp_path / "xnative_dot.f90"
    native_source.write_text(
        'subroutine dot_c(nx, x, ny, y, out) bind(C, name="dot_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: nx, ny\n"
        "  real(c_double), intent(in) :: x(nx), y(ny)\n"
        "  real(c_double), intent(out) :: out\n"
        "  integer :: i, n\n"
        "  n = min(nx, ny)\n"
        "  out = 0.0_c_double\n"
        "  do i = 1, n\n"
        "    out = out + x(i)*y(i)\n"
        "  end do\n"
        "end subroutine dot_c\n",
        encoding="utf-8",
    )
    source.write_text(
        f"!$ofort native dot2={native_dll}:dot_c,r8arr_r8arr_r8\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(3), y(3), z\n"
        "x = [1.0_dp, 2.0_dp, 3.0_dp]\n"
        "y = [10.0_dp, 20.0_dp, 30.0_dp]\n"
        "z = dot2(x, y)\n"
        "print *, z\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert abs(float(result.stdout.split()[0]) - 140.0) < 1.0e-12


def test_native_subroutine_directive_can_transform_matrices(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_gram.f90"
    native_dll = tmp_path / "native_gram.dll"
    source = tmp_path / "xnative_gram.f90"
    native_source.write_text(
        'subroutine gram_c(nx1, nx2, x, ny1, ny2, y) bind(C, name="gram_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: nx1, nx2, ny1, ny2\n"
        "  real(c_double), intent(in) :: x(nx1,nx2)\n"
        "  real(c_double), intent(out) :: y(ny1,ny2)\n"
        "  integer :: i, j, k\n"
        "  y = 0.0_c_double\n"
        "  do j = 1, min(ny2, nx2)\n"
        "    do i = 1, min(ny1, nx2)\n"
        "      do k = 1, nx1\n"
        "        y(i,j) = y(i,j) + x(k,i)*x(k,j)\n"
        "      end do\n"
        "    end do\n"
        "  end do\n"
        "end subroutine gram_c\n",
        encoding="utf-8",
    )
    source.write_text(
        f"!$ofort native gram={native_dll}:gram_c,r8mat_r8mat\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(2,2), y(2,2)\n"
        "x = reshape([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp], [2, 2])\n"
        "call gram(x, y)\n"
        "print *, y\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    fields = [float(x) for x in result.stdout.split()]
    assert fields == [5.0, 11.0, 11.0, 25.0]


def test_native_function_directive_can_return_array_from_integer_size(tmp_path):
    gfortran = shutil.which("gfortran")
    if not gfortran:
        pytest.skip("gfortran is required to build the native Fortran test DLL")

    native_source = tmp_path / "native_seq.f90"
    native_dll = tmp_path / "native_seq.dll"
    source = tmp_path / "xnative_seq.f90"
    native_source.write_text(
        'subroutine seq_c(n, ny, y) bind(C, name="seq_c")\n'
        "  use iso_c_binding\n"
        "  implicit none\n"
        "  integer(c_int), intent(in) :: n, ny\n"
        "  real(c_double), intent(out) :: y(ny)\n"
        "  integer :: i\n"
        "  y = 0.0_c_double\n"
        "  do i = 1, min(n, ny)\n"
        "    y(i) = 10.0_c_double*real(i, c_double)\n"
        "  end do\n"
        "end subroutine seq_c\n",
        encoding="utf-8",
    )
    source.write_text(
        f"!$ofort native seq={native_dll}:seq_c,i4_r8arr\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp) :: x(4)\n"
        "x = seq(4)\n"
        "print *, size(x), x\n"
        "end\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [gfortran, "-shared", "-O2", str(native_source), "-o", str(native_dll)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if build.returncode != 0:
        pytest.skip(f"could not build native Fortran test DLL: {build.stderr}")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["4", "10.0", "20.0", "30.0", "40.0"]


def test_native_subroutine_rejects_unknown_abi(tmp_path):
    source = tmp_path / "xnative_bad_abi.f90"
    source.write_text("print *, 1\nend\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--native", f"stats={tmp_path / 'missing.dll'}:stats_c,bad_abi", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "unsupported native ABI 'bad_abi'" in result.stderr


def test_profile_lines_reports_statement_times(tmp_path):
    source = tmp_path / "xprofile.f90"
    source.write_text(
        "integer :: i\n"
        "i = 2\n"
        "print *, i**5\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--profile-lines", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "32\n"
    assert "line profile:" in result.stderr
    assert re.search(r"(?m)^\s*2\s+1\s+\d+\.\d{6}\s+i = 2$", result.stderr)
    assert re.search(r"(?m)^\s*3\s+1\s+\d+\.\d{6}\s+print \*, i\*\*5$", result.stderr)


def test_profile_procs_reports_user_procedure_times(tmp_path):
    source = tmp_path / "xprofile_procs.f90"
    source.write_text(
        "program xprofile_procs\n"
        "print *, twice(21)\n"
        "contains\n"
        "integer function twice(i)\n"
        "integer, intent(in) :: i\n"
        "twice = 2*i\n"
        "end function twice\n"
        "end program xprofile_procs\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "42\n"
    assert "procedure profile:" in result.stderr
    assert re.search(r"(?m)^\s*1\s+\d+\.\d{6}\s+twice$", result.stderr)


def test_time_option_reports_check_time_without_changing_stdout(tmp_path):
    source = tmp_path / "xcheck_time.f90"
    source.write_text(
        "program xcheck_time\n"
        "print *, 12345\n"
        "end program xcheck_time\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--time", "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ofort check passed\n"
    assert re.search(r"(?m)^time: \d+\.\d{6} s$", result.stderr)


def assert_time_detail(stderr):
    assert re.search(
        r"(?m)^time:\n"
        r"  setup:    \d+\.\d{6} s\n"
        r"  lex:      \d+\.\d{6} s\n"
        r"  parse:    \d+\.\d{6} s\n"
        r"  register: \d+\.\d{6} s\n"
        r"  execute:  \d+\.\d{6} s\n"
        r"  total:    \d+\.\d{6} s$",
        stderr,
    )


def test_time_detail_option_reports_execution_breakdown_without_changing_stdout():
    source = CASES / "xtry.f90"
    result = subprocess.run(
        [str(OFORT), "--time-detail", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert_time_detail(result.stderr)


def test_time_detail_option_reports_check_breakdown_without_changing_stdout(tmp_path):
    source = tmp_path / "xcheck_time_detail.f90"
    source.write_text(
        "program xcheck_time_detail\n"
        "print *, 12345\n"
        "end program xcheck_time_detail\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--time-detail", "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ofort check passed\n"
    assert_time_detail(result.stderr)


def test_repl_warns_when_implicit_save_line_is_entered(tmp_path):
    source = tmp_path / "empty.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="subroutine s()\ninteger :: n = 0\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: local variable 'n' has implicit SAVE due to initialization" in result.stderr


def test_repl_nologo_suppresses_startup_banner(tmp_path):
    source = tmp_path / "repl_nologo.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=".quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "Enter Fortran source." not in result.stdout
    assert "Commands:" not in result.stdout
    assert "> " in result.stdout


def test_repl_prompt_option_sets_prompt_text(tmp_path):
    source = tmp_path / "repl_prompt.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", ">", "--load", str(source)],
        cwd=ROOT,
        input=".quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "ofort> " not in result.stdout
    assert ">" in result.stdout


def test_repl_prompt_command_changes_prompt_during_session(tmp_path):
    source = tmp_path / "repl_prompt_command.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=".prompt \">\"\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "> >" in result.stdout


def test_repl_saveq_saves_to_named_file_and_quits(tmp_path):
    source = tmp_path / "repl_saveq.f90"
    output = tmp_path / "saved_program.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=tmp_path,
        input=f"integer :: i\ni = 7\n.saveq {output.name}\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert f"Saved {output.name}" in result.stdout
    saved = output.read_text(encoding="utf-8")
    assert "integer :: i\n" in saved
    assert "i = 7\n" in saved
    assert saved.rstrip().endswith("end")


def test_repl_save_named_file_requires_overwrite(tmp_path):
    source = tmp_path / "repl_save_overwrite.f90"
    output = tmp_path / "saved_program.f90"
    source.write_text("", encoding="utf-8")
    output.write_text("old\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=tmp_path,
        input=(
            f"integer :: i\n"
            f"i = 7\n"
            f".save {output.name}\n"
            f".saveq {output.name} --overwrite\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert f"{output.name} already exists; use --overwrite to replace it" in result.stderr
    assert output.read_text(encoding="utf-8") != "old\n"
    assert "i = 7\n" in output.read_text(encoding="utf-8")


def test_repl_quit_bang_quits_without_saving(tmp_path):
    source = tmp_path / "repl_quit_bang.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=tmp_path,
        input="integer :: i\ni = 7\n.quit!\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "main.f90").exists()


def test_w_option_suppresses_repl_implicit_save_warning(tmp_path):
    source = tmp_path / "empty.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "-w", "--load", str(source)],
        cwd=ROOT,
        input="subroutine s()\ninteger :: n = 0\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_repl_run_repeats_with_command_arguments(tmp_path):
    source = tmp_path / "xrun.f90"
    source.write_text(
        "program xrun\n"
        "implicit none\n"
        "print *, command_argument_count()\n"
        "end program xrun\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".run 2 -- aa bb\n.runq 1 -- cc\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numeric_lines = re.findall(r"(?m)^(?:(?:ofort>|>)\s*)?([0-9]+)$", result.stdout)
    assert numeric_lines == ["2", "2", "1"]


def test_repl_time_repeats_and_prints_summary(tmp_path):
    source = tmp_path / "xtime.f90"
    source.write_text(
        "program xtime\n"
        "print *, 123\n"
        "end program xtime\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".time 2\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numeric_lines = re.findall(r"(?m)^(?:(?:ofort>|>)\s*)?(123)$", result.stdout)
    assert numeric_lines == ["123", "123"]
    assert re.search(r"(?m)^\s+total\s+avg\s+sd\s+min\s+max$", result.stdout)
    assert re.search(
        r"(?m)^\s*\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6} s$",
        result.stdout,
    )


def test_repl_time_single_run_prints_only_total(tmp_path):
    source = tmp_path / "xtime1.f90"
    source.write_text(
        "program xtime1\n"
        "print *, 456\n"
        "end program xtime1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".time\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert re.search(r"(?m)^(?:(?:ofort>|>)\s*)?456$", result.stdout)
    assert re.search(r"(?m)^\s+total$", result.stdout)
    assert re.search(r"(?m)^\s*\d+\.\d{6} s$", result.stdout)
    assert not re.search(r"(?m)^\s+total\s+avg\s+sd\s+min\s+max$", result.stdout)


def test_repl_vars_lists_all_and_selected_values(tmp_path):
    source = tmp_path / "xvars.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x\n"
            "i = 2\n"
            "x = 3.5\n"
            ".vars\n"
            ".vars i x missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("i = 2") == 2
    assert result.stdout.count("x = 3.5") == 2
    assert "missing: undefined" in result.stdout


def test_repl_info_lists_declaration_style_details(tmp_path):
    source = tmp_path / "xinfo.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            ".info\n"
            ".info x i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("integer i: 2") == 2
    assert result.stdout.count("real x(5): 1.0 2.0 3.0 4.0 5.0") == 2
    assert "missing: undefined" in result.stdout


def test_repl_shapes_lists_array_shapes(tmp_path):
    source = tmp_path / "xshapes.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "real :: y(3,2)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            "y = [1,2,3,4,5,6]\n"
            ".shapes\n"
            ".shapes x y i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("x: 5") == 2
    assert result.stdout.count("y: 3 2") == 2
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_sizes_lists_array_sizes(tmp_path):
    source = tmp_path / "xsizes.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "real :: y(3,2)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            "y = [1,2,3,4,5,6]\n"
            ".sizes\n"
            ".sizes x y i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("x: 5") == 2
    assert result.stdout.count("y: 6") == 2
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_stats_lists_grouped_array_tables(tmp_path):
    source = tmp_path / "xstats.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "integer :: ia(5)\n"
            "real :: x(5)\n"
            "i = 2\n"
            "ia = [1,2,3,4,5]\n"
            "x = [2,4,6,8,10]\n"
            ".stats\n"
            ".stats x ia i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("integer arrays") == 2
    assert result.stdout.count("real arrays") == 2
    assert result.stdout.count("name                 size") == 4
    assert re.search(r"(?m)^ia\s+5\s+1\s+5\s+3\s+1\.581139\s+1\s+5$", result.stdout)
    assert re.search(r"(?m)^x\s+5\s+2\s+10\s+6\s+3\.162278\s+2\s+10$", result.stdout)
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_del_deletes_lines_and_ranges(tmp_path):
    source = tmp_path / "xdel.f90"
    source.write_text(
        "program xdel\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "i = 2\n"
        "print *, i\n"
        "end program xdel\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del 5\n.del 3:4\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  program xdel\n" in result.stdout
    assert "   2    implicit none\n" in result.stdout
    assert "   3    integer :: i\n" in result.stdout
    assert "   4    print *, i\n" in result.stdout
    assert "   5  end program xdel\n" in result.stdout
    assert "   4    i = 1\n" not in result.stdout
    assert "i = 2" not in result.stdout


def test_repl_del_open_ended_ranges(tmp_path):
    source = tmp_path / "xdelopen.f90"
    source.write_text(
        "program xdelopen\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "end program xdelopen\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del :2\n.list\n.del 2:\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  implicit none\n" in result.stdout
    assert "   2  i = 1\n" in result.stdout
    assert "   3  print *, i\n" in result.stdout
    assert "end program xdelopen" in result.stdout
    assert "   3  end program xdelopen\n" in result.stdout


def test_repl_del_rejects_footer_line(tmp_path):
    source = tmp_path / "xdelfooter.f90"
    source.write_text(
        "program xdelfooter\n"
        "print *, 1\n"
        "end program xdelfooter\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del 3\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".del range is outside the editable source buffer" in result.stderr
    assert "   4  end program xdelfooter\n" in result.stdout


def test_repl_ins_and_rep_edit_lines(tmp_path):
    source = tmp_path / "xedit.f90"
    source.write_text(
        "program xedit\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "end program xedit\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            ".ins 3 integer :: j\n"
            ".rep 4 i = 10\n"
            ".ins 6 print *, i\n"
            ".list\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  program xedit\n" in result.stdout
    assert "   2    implicit none\n" in result.stdout
    assert "   3    integer :: i\n" in result.stdout
    assert "   4    integer :: j\n" in result.stdout
    assert "   5    i = 10\n" in result.stdout
    assert "   6    print *, i\n" in result.stdout
    assert "   7    print *, i\n" in result.stdout
    assert "   8  end program xedit\n" in result.stdout
    assert "   4    i = 1\n" not in result.stdout


def test_repl_ins_rep_reject_footer_line(tmp_path):
    source = tmp_path / "xeditfooter.f90"
    source.write_text(
        "program xeditfooter\n"
        "print *, 1\n"
        "end program xeditfooter\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rep 3 end\n.ins 4 print *, 2\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rep line is outside the editable source buffer" in result.stderr
    assert ".ins line is outside the editable source buffer" in result.stderr
    assert "   4  end program xeditfooter\n" in result.stdout


def test_repl_rename_variable_tokens(tmp_path):
    source = tmp_path / "xrename.f90"
    source.write_text(
        "program xrename\n"
        "integer :: i\n"
        "integer :: idx\n"
        "i = 2\n"
        "print *, i, idx\n"
        "print *, \"i should stay\"\n"
        "! i should stay in comment\n"
        "end program xrename\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename i j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "integer :: j" in result.stdout
    assert "integer :: idx" in result.stdout
    assert "j = 2" in result.stdout
    assert "print *, j, idx" in result.stdout
    assert '"i should stay"' in result.stdout
    assert "! i should stay in comment" in result.stdout
    assert "   2    integer :: i\n" not in result.stdout
    assert "   4    i = 2\n" not in result.stdout


def test_repl_rename_rejects_existing_name(tmp_path):
    source = tmp_path / "xrename_conflict.f90"
    source.write_text(
        "program xrename_conflict\n"
        "integer :: i\n"
        "integer :: j\n"
        "i = 2\n"
        "end program xrename_conflict\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename i j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rename: j already exists" in result.stderr
    assert "integer :: i" in result.stdout
    assert "integer :: j" in result.stdout
    assert "i = 2" in result.stdout


def test_repl_rename_rejects_missing_old_name(tmp_path):
    source = tmp_path / "xrename_missing.f90"
    source.write_text(
        "program xrename_missing\n"
        "integer :: i\n"
        "i = 2\n"
        "end program xrename_missing\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename k j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rename: k not found" in result.stderr
    assert "integer :: i" in result.stdout
    assert "i = 2" in result.stdout


def test_repl_decl_lists_declaration_lines(tmp_path):
    source = tmp_path / "xdecl.f90"
    source.write_text(
        "program xdecl\n"
        "implicit none\n"
        "integer :: i\n"
        "real :: x(2)\n"
        "i = 2\n"
        "print *, i\n"
        "end program xdecl\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".decl\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   2    implicit none\n" in result.stdout
    assert "   3    integer :: i\n" in result.stdout
    assert "   4    real :: x(2)\n" in result.stdout
    assert "i = 2" not in result.stdout
    assert "print *, i" not in result.stdout


def test_repl_list_auto_indents_blocks(tmp_path):
    source = tmp_path / "xindent.f90"
    source.write_text(
        "program x\n"
        "integer :: i\n"
        "do i = 1, 2\n"
        "if (i == 1) then\n"
        "print *, i\n"
        "else\n"
        "print *, -i\n"
        "end if\n"
        "end do\n"
        "end program x\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   3    integer :: i\n" in result.stdout
    assert "   4    do i = 1, 2\n" in result.stdout
    assert "   5      if (i == 1) then\n" in result.stdout
    assert "   6        print *, i\n" in result.stdout
    assert "   7      else\n" in result.stdout
    assert "   9      end if\n" in result.stdout
    assert "  10    end do\n" in result.stdout
    assert "  11  end program x\n" in result.stdout


def test_rejects_type_changing_assignment():
    source = CASES / "xtype_change.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Cannot assign CHARACTER to INTEGER variable 'i'" in result.stderr
    assert 'line 4: i = "a"' in result.stderr


def test_repl_list_dash_n_omits_line_numbers(tmp_path):
    source = tmp_path / "repl_list_no_numbers.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input="integer :: i\ni = 7\n.list -n\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: i\n" in result.stdout
    assert "i = 7\n" in result.stdout
    assert "   1  integer :: i\n" not in result.stdout
    assert "   2  i = 7\n" not in result.stdout


def test_repl_group_decl_groups_simple_declarations(tmp_path):
    source = tmp_path / "repl_group_decl.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "logical :: tf1\n"
            "integer :: j\n"
            "logical :: tf2\n"
            ".group-decl\n"
            ".list -n\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: i, j\n" in result.stdout
    assert "logical :: tf1, tf2\n" in result.stdout
    assert "integer :: j\n" not in result.stdout
    assert "logical :: tf2\n" not in result.stdout


def test_repl_unused_lists_unused_simple_declarations(tmp_path):
    source = tmp_path / "repl_unused.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i, j\n"
            "logical :: tf1, tf2\n"
            "i = 3\n"
            "tf1 = .true.\n"
            "print *, i, tf1\n"
            ".unused\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "unused declarations:\n" in result.stdout
    assert "  j\n" in result.stdout
    assert "  tf2\n" in result.stdout
    assert "  i\n" not in result.stdout
    assert "  tf1\n" not in result.stdout


def test_repl_undecl_removes_named_simple_declarations(tmp_path):
    source = tmp_path / "repl_undecl.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i, j, k\n"
            "logical :: tf1, tf2\n"
            ".undecl j tf2\n"
            ".list -n\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: i, k\n" in result.stdout
    assert "logical :: tf1\n" in result.stdout
    assert "integer :: i, j, k\n" not in result.stdout
    assert "logical :: tf1, tf2\n" not in result.stdout


def test_repl_drop_unused_removes_unused_simple_declarations(tmp_path):
    source = tmp_path / "repl_drop_unused.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i, j\n"
            "logical :: tf1, tf2\n"
            "i = 3\n"
            "tf1 = .true.\n"
            "print *, i, tf1\n"
            ".drop-unused\n"
            ".list -n\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: i\n" in result.stdout
    assert "logical :: tf1\n" in result.stdout
    assert "integer :: i, j\n" not in result.stdout
    assert "logical :: tf1, tf2\n" not in result.stdout


def test_repl_print_shortcut_is_stored_as_fortran(tmp_path):
    source = tmp_path / "repl_print_shortcut.f90"
    source.write_text("integer :: i = 2\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="print i,i+1,\"x\"\n.list\n.\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "   3  print *, i,i+1,\"x\"\n" in result.stdout
    assert "2 3 x\n" in result.stdout


def test_repl_print_quoted_format_is_not_rewritten(tmp_path):
    source = tmp_path / "repl_print_quoted_format.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input='real :: x\nx = 0.5\nprint "(f8.3)", x\n.list\n.\n.quit!\n',
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert 'print "(f8.3)", x\n' in result.stdout
    assert "(f8.3) 0." not in result.stdout
    assert "   0.500" in result.stdout


def test_repl_inserts_colons_in_simple_declarations(tmp_path):
    source = tmp_path / "repl_decl_colons.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer n\n"
            "real x(2)\n"
            "real, allocatable y(:)\n"
            "double precision z(2)\n"
            "type(foo) obj\n"
            ".list -n\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: n" in result.stdout
    assert "real :: x(2)" in result.stdout
    assert "real, allocatable :: y(:)" in result.stdout
    assert "double precision :: z(2)" in result.stdout
    assert "type(foo) :: obj" in result.stdout


def test_repl_rewrites_mixed_length_character_constructor(tmp_path):
    source = tmp_path / "repl_char_constructor_shortcut.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "character(len=10) :: s(3)\n"
            "s = [\"one\", \"four\", \"seven\"]\n"
            "print *, s\n"
            ".\n"
            ".list\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: rewrote mixed-length character constructor as character(len=5)" in result.stderr
    assert "one        four       seven" in result.stdout
    assert "s = [character(len=5) :: \"one\", \"four\", \"seven\"]" in result.stdout


def test_repl_warns_about_character_truncation(tmp_path):
    source = tmp_path / "repl_char_truncation.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "character (len=3) :: s(4)\n"
            "s = [character(len=5) :: \"one  \", \"four \", \"seven\", \"eight\"]\n"
            "print *, s\n"
            ".\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: assigning CHARACTER value to CHARACTER(LEN=3) variable 's' truncates" in result.stderr
    assert "one fou sev eig" in result.stdout


def test_repl_rejects_uninitialized_variable_read(tmp_path):
    source = tmp_path / "repl_uninitialized.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="integer i\nprint *, i\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "Variable 'i' is used before it is set" in result.stderr
    assert "line 1: print *, i" in result.stderr


def test_repl_rejects_uninitialized_variable_in_assignment_rhs(tmp_path):
    source = tmp_path / "repl_uninitialized_assignment.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="integer :: i, j\nj = 2*i\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "Variable 'i' is used before it is set" in result.stderr
    assert "line 1: j = 2*i" in result.stderr


def test_repl_random_number_marks_harvest_initialized(tmp_path):
    source = tmp_path / "repl_random_number_initialized.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "double precision x(3)\n"
            "call random_number(x)\n"
            "x\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "Variable 'x' is used before it is set" not in result.stderr


def test_fast_do_loop_index_is_initialized(tmp_path):
    source = tmp_path / "xfast_do_loop_index_initialized.f90"
    source.write_text(
        "implicit none\n"
        "integer :: i, x(3)\n"
        "x = 0\n"
        "do i = 2, 3\n"
        "  x(i) = x(i) + x(i-1) + i\n"
        "end do\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "used before it is set" not in result.stderr
    assert result.stdout.split() == ["0", "2", "5"]


def test_repl_allows_inquiry_intrinsics_on_uninitialized_variables(tmp_path):
    source = tmp_path / "repl_uninitialized_inquiries.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: v(2)\n"
            "print *, kind(v)\n"
            "print *, size(v)\n"
            "print *, lbound(v)\n"
            "print *, ubound(v)\n"
            "print *, shape(v)\n"
            "print *, rank(v)\n"
            ".\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numbers = [tok for tok in result.stdout.split() if re.fullmatch(r"-?\d+", tok)]
    assert numbers[-6:] == ["4", "2", "1", "2", "2", "1"]


def test_repl_allocate_mold_allows_uninitialized_mold_variable(tmp_path):
    source = tmp_path / "repl_allocate_mold.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "real :: x(3)\n"
            "real, allocatable :: y(:)\n"
            "allocate (y, mold=x)\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_repl_dot_replays_allocate_in_fresh_interpreter(tmp_path):
    source = tmp_path / "repl_allocate_replay.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "real :: x(3)\n"
            "real, allocatable :: y(:)\n"
            "allocate (y(size(x)))\n"
            "print *, shape(x), shape(y)\n"
            ".\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numbers = [tok for tok in result.stdout.split() if re.fullmatch(r"-?\d+", tok)]
    assert numbers[-2:] == ["3", "3"]


def test_repl_gfortran_command_compiles_and_runs_buffer(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .gfortran")

    source = tmp_path / "repl_gfortran.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 21\n"
            "print *, 2*n\n"
            ".gfortran\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "42" in result.stdout.split()


def test_repl_gfortran_command_accepts_options_and_compile_only(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .gfortran")

    source = tmp_path / "repl_gfortran_compile_only.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "print *, 99\n"
            ".gfortran -O3 -c\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "99" not in result.stdout.split()
    assert ".gfortran: compile failed" not in result.stderr


def test_repl_compiler_commands_can_be_chained_with_semicolon(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .gfortran")

    source = tmp_path / "repl_gfortran_chain.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "print *, 77\n"
            ".gfortran -O3 -c; .gfortran -O0\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split().count("77") == 1


def test_repl_ofort_can_be_chained_with_external_compiler(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .gfortran")

    source = tmp_path / "repl_ofort_gfortran_chain.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 12\n"
            "print *, n + 1\n"
            ".ofort; .gfortran -O0\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split().count("13") == 2


def test_repl_timec_times_ofort_command(tmp_path):
    source = tmp_path / "repl_timec_ofort.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "print *, 31\n"
            ".timec .ofort\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "command" in result.stdout
    assert "compile_s" in result.stdout
    assert "run_s" in result.stdout
    assert "total_s" in result.stdout
    assert ".ofort" in result.stdout
    assert "ok" in result.stdout
    assert "31" in result.stdout.split()


def test_repl_timec_times_chained_compiler_commands(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .gfortran")

    source = tmp_path / "repl_timec_chain.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "print *, 32\n"
            ".timec 1 .ofort; .gfortran -O0\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "compile_s" in result.stdout
    assert "run_s" in result.stdout
    assert "total_s" in result.stdout
    assert ".ofort" in result.stdout
    assert ".gfortran -O0" in result.stdout
    assert result.stdout.split().count("32") == 2


def test_repl_timec_accepts_ofort_fast_option(tmp_path):
    source = tmp_path / "repl_timec_ofort_fast.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 33\n"
            "print *, n\n"
            ".timec 1 .ofort --fast\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert ".ofort --fast" in result.stdout
    assert "failed" not in result.stdout
    assert "33" in result.stdout.split()


def test_repl_timec_accepts_bare_compiler_names(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required for .timec gfortran")

    source = tmp_path / "repl_timec_bare_names.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 34\n"
            "print *, n\n"
            ".timec 1 ofort --fast; gfortran -O0\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "ofort --fast" in result.stdout
    assert "gfortran -O0" in result.stdout
    assert "failed" not in result.stdout
    assert result.stdout.split().count("34") == 2


def test_repl_auto_end_inserts_and_advances_out_of_blocks(tmp_path):
    source = tmp_path / "repl_auto_end.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--auto-end", "--load", str(source)],
        cwd=ROOT,
        input=(
            "program main\n"
            "integer :: i\n"
            "do i = 1, 2\n"
            "print *, i\n"
            "end do\n"
            "print *, 99\n"
            "end program main\n"
            ".list\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("end do\n") == 1
    assert result.stdout.count("end program main\n") == 1
    assert result.stdout.find("do i = 1, 2") < result.stdout.find("print *, i")
    assert result.stdout.find("print *, i") < result.stdout.find("end do")
    assert result.stdout.find("end do") < result.stdout.find("print *, 99")
    assert result.stdout.find("print *, 99") < result.stdout.find("end program main")
    assert result.stdout.split().count("1") >= 1
    assert result.stdout.split().count("2") >= 1
    assert "99" in result.stdout.split()


def test_repl_defer_check_accepts_lines_until_run(tmp_path):
    source = tmp_path / "repl_defer_check.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--defer-check", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n + 10\n"
            ".list\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "integer :: n + 10" in result.stdout
    assert "Syntax error" in result.stderr


def test_repl_autorun_runs_after_top_level_executable_line(tmp_path):
    source = tmp_path / "repl_autorun.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--autorun", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 21\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""

    source.write_text("", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--autorun", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "n = 21\n"
            "print *, n\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split().count("21") >= 1


def test_repl_save_and_load_state_restores_simple_variables(tmp_path):
    source = tmp_path / "repl_state.f90"
    state = tmp_path / "state.of90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: n\n"
            "real :: x(2)\n"
            "character(len=5) :: s\n"
            "n = 7\n"
            "x = [1.5, 2.5]\n"
            "s = \"abc\"\n"
            "end\n"
            f".save-state {state}\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert state.exists()

    source.write_text("", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            f".load-state {state}\n"
            ".vars n x s\n"
            ".list -n\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "n = 7" in result.stdout
    assert "x = 1.5 2.5" in result.stdout
    assert "s = abc" in result.stdout
    assert "integer :: n" in result.stdout
    assert "real :: x(2)" in result.stdout


def test_repl_save_state_preserves_parameters_and_real_kind(tmp_path):
    source = tmp_path / "repl_state_kind.f90"
    state = tmp_path / "state_kind.of90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer, parameter :: dp = kind(1.0d0), n = 4\n"
            "real(dp) :: x(n)\n"
            "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
            "end\n"
            f".save-state {state}\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = state.read_text(encoding="utf-8")
    assert "integer, parameter :: dp = 8" in text
    assert "integer, parameter :: n = 4" in text
    assert "real(kind=dp) :: x(n)" in text

    source.write_text("", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            f".load-state {state}\n"
            "print *, dp, n, kind(x)\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-3:] == ["8", "4", "8"]


def test_repl_accepts_pasted_prompted_lines(tmp_path):
    source = tmp_path / "repl_pasted_prompt.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "> const dp = kind(1.0d0), n = 10\n"
            "> real(dp) x(n)\n"
            "> call random_number(x)\n"
            "> print*,kind(x),size(x)\n"
            "> .\n"
            "ofort> .quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["8", "10"]


def test_repl_save_state_binary_arrays_round_trips(tmp_path):
    source = tmp_path / "repl_state_binary.f90"
    state = tmp_path / "state_binary.f90"
    data_dir = tmp_path / "state_binary_data"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer, parameter :: dp = kind(1.0d0), n = 4\n"
            "real(dp) :: x(n)\n"
            "x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]\n"
            "print *, sum(x)\n"
            "end\n"
            f".save-state {state} --binary-arrays --array-threshold 1\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert state.exists()
    assert (data_dir / "x.bin").exists()
    text = state.read_text(encoding="utf-8")
    assert "open(newunit=ofort_state_unit" in text
    assert "read(ofort_state_unit) x" in text
    assert "print *, sum(x)" in text

    source.write_text("", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            f".load-state {state}\n"
            "print *, kind(x), size(x), sum(x)\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-3:] == ["8", "4", "10.0"]


def test_cache_option_creates_and_reuses_source_cache(tmp_path):
    source = tmp_path / "xcache.f90"
    source.write_text(
        "program xcache\n"
        "implicit none\n"
        "print *, 42\n"
        "end program xcache\n",
        encoding="utf-8",
    )

    for _ in range(2):
        result = subprocess.run(
            [str(OFORT), "--cache", str(source)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["42"]

    cache_dir = tmp_path / ".ofort_cache"
    assert cache_dir.exists()
    assert list(cache_dir.glob("*.f90"))
    assert list(cache_dir.glob("*.meta"))


def test_repl_let_const_shortcuts_are_stored_as_fortran(tmp_path):
    source = tmp_path / "repl_let_const_shortcut.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "let i = 2\n"
            "let x = 2.5\n"
            "let s = \"abc\"\n"
            "const n = 10\n"
            "const ok = .true.\n"
            ".list\n"
            "print i,x,s,n,ok\n"
            ".\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer :: i\n" in result.stdout
    assert "i = 2\n" in result.stdout
    assert "real :: x\n" in result.stdout
    assert "x = 2.5\n" in result.stdout
    assert "character(len=3) :: s\n" in result.stdout
    assert "s = \"abc\"\n" in result.stdout
    assert "integer, parameter :: n = 10\n" in result.stdout
    assert "logical, parameter :: ok = .true.\n" in result.stdout
    assert "2 2.5 abc 10 T\n" in result.stdout


def test_repl_const_kind_shortcut_is_integer_parameter(tmp_path):
    source = tmp_path / "repl_const_kind_shortcut.f90"
    source.write_text("implicit none\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="const dp = kind(1.0d0)\n.list\nprint dp\n.\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "integer, parameter :: dp = kind(1.0d0)\n" in result.stdout
    assert "8\n" in result.stdout


def test_repl_const_shortcut_supports_array_parameters(tmp_path):
    source = tmp_path / "repl_const_array_shortcut.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "const n = 3\n"
            "const v(n) = [10, 20, 30]\n"
            "print *, v\n"
            ".\n"
            ".list\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "10 20 30" in " ".join(result.stdout.split())
    assert "integer, parameter :: v(n) = [10, 20, 30]" in result.stdout


def test_repl_let_const_existing_names_and_reconst(tmp_path):
    source = tmp_path / "repl_reconst_shortcut.f90"
    source.write_text("implicit none\n", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "const n = 4\n"
            "let m = 5\n"
            "n*m\n"
            "let m = 7\n"
            "const n = 8\n"
            "reconst n = 8\n"
            "n*m\n"
            ".list\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "LET variable 'm' already exists; use assignment: m = ..." in result.stderr
    assert "CONST name 'n' already exists; use reconst n = ... to replace a parameter" in result.stderr
    assert "> 20\n" in result.stdout
    assert "> 40\n" in result.stdout
    assert "integer, parameter :: n = 8\n" in result.stdout
    assert result.stdout.count("integer :: m\n") == 1
    assert "m = 5\n" in result.stdout
    assert "m = 7\n" not in result.stdout


def test_repl_reconst_preserves_other_parameters_on_same_line(tmp_path):
    source = tmp_path / "repl_reconst_multidecl.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "const dp = kind(1.0d0), n = 10**3\n"
            "real(dp) x(n)\n"
            "reconst n = 10**4\n"
            ".list\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "integer, parameter :: dp = kind(1.0d0), n = 10**4\n" in result.stdout
    assert "real(dp) :: x(n)\n" in result.stdout


def test_repl_implicit_none_first_line_has_no_spurious_text(tmp_path):
    source = tmp_path / "repl_implicit_none.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="implicit none\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  implicit none\n" in result.stdout
    assert "   2  P\n" not in result.stdout


def test_repl_defaults_to_implicit_none(tmp_path):
    source = tmp_path / "repl_default_implicit_none.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--nologo", "--prompt", "", "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "i = 4\n"
            "print *, i\n"
            ".list\n"
            ".\n"
            ".quit!\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "   1  implicit none\n" in result.stdout
    assert "4" in result.stdout.split()


def test_repl_malformed_let_const_are_not_shortcuts(tmp_path):
    source = tmp_path / "repl_bad_let_const_shortcut.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="let = 3\nconst = .true.\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "Undefined variable 'let'" in result.stderr
    assert "Undefined variable 'const'" in result.stderr
    assert "   1  implicit none\n" in result.stdout


def test_pure_procedure_rejects_io(tmp_path):
    source = tmp_path / "xpure_io.f90"
    source.write_text(
        """
module m
implicit none
contains
pure subroutine s()
print*,"in s"
end subroutine s
end module m

program main
implicit none
use m
call s()
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "PRINT statement is not allowed in PURE procedure 's'" in result.stderr
    assert 'line 5: print*,"in s"' in result.stderr


def test_pure_procedure_rejects_random_number(tmp_path):
    source = tmp_path / "xpure_random_number.f90"
    source.write_text(
        """
module m
implicit none
contains
pure subroutine s()
real :: x
call random_number(x)
end subroutine s
end module m

program main
implicit none
use m
call s()
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Impure intrinsic subroutine 'random_number' is not allowed in PURE procedure 's'" in result.stderr
    assert "line 6: call random_number(x)" in result.stderr


def test_pure_procedure_reports_multiple_violations(tmp_path):
    source = tmp_path / "xpure.f90"
    source.write_text(
        """
module m
implicit none
real :: y
contains
pure subroutine s1()
print*,"in s1"
end subroutine s1

pure subroutine s2()
real :: x
call random_number(x)
end subroutine s2

pure subroutine s3()
y = 0.0
end subroutine s3

pure subroutine s4()
integer :: n
call random_seed(size=n)
end subroutine s4
end module m

program main
implicit none
use m
call s1()
call s2()
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "PRINT statement is not allowed in PURE procedure 's1'" in result.stderr
    assert 'line 6: print*,"in s1"' in result.stderr
    assert "Impure intrinsic subroutine 'random_number' is not allowed in PURE procedure 's2'" in result.stderr
    assert "line 11: call random_number(x)" in result.stderr
    assert "Variable 'y' cannot appear in a variable definition context in PURE procedure 's3'" in result.stderr
    assert "line 15: y = 0.0" in result.stderr
    assert "Impure intrinsic subroutine 'random_seed' is not allowed in PURE procedure 's4'" in result.stderr
    assert "line 20: call random_seed(size=n)" in result.stderr


def test_matmul_matrix_vector_and_vector_matrix(tmp_path):
    source = tmp_path / "xmatmul_vector.f90"
    source.write_text(
        """
program main
implicit none
real(8) :: a(2,3), b(3,2), x(3), y(3)
a = reshape([1.0d0,2.0d0,3.0d0,4.0d0,5.0d0,6.0d0], [2,3])
b = reshape([1.0d0,2.0d0,3.0d0,4.0d0,5.0d0,6.0d0], [3,2])
x = [10.0d0,20.0d0,30.0d0]
y = [10.0d0,20.0d0,30.0d0]
print *, matmul(a, x)
print *, matmul(y, b)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "220.0 280.0\n140.0 320.0\n"


def test_ofort_statistics_mod_vector_functions(tmp_path):
    source = tmp_path / "xofort_statistics_mod.f90"
    source.write_text(
        """
program main
use ofort_statistics_mod, only: mean, variance, sd, cov, cor, variance_given_mean, sd_given_mean
implicit none
real(8) :: x(4), y(4)
real(8) :: xm
x = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
y = [2.0d0, 4.0d0, 6.0d0, 8.0d0]
xm = mean(x)
print *, mean(x)
print *, variance(x)
print *, sd(x)
print *, cov(x, y)
print *, cor(x, y)
print *, variance_given_mean(x, xm)
print *, sd_given_mean(x, xm)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(2.5)
    assert float(lines[1]) == pytest.approx(1.6666666666666667)
    assert float(lines[2]) == pytest.approx(1.2909944487358056)
    assert float(lines[3]) == pytest.approx(3.3333333333333335)
    assert float(lines[4]) == pytest.approx(1.0)
    assert float(lines[5]) == pytest.approx(1.6666666666666667)
    assert float(lines[6]) == pytest.approx(1.2909944487358056)


def test_stdlib_stats_subset_maps_to_ofort_statistics(tmp_path):
    source = tmp_path / "xstdlib_stats_subset.f90"
    source.write_text(
        """
program main
use stdlib_stats, only: mean, var, cov, corr
implicit none
real(8) :: x(4), y(4), z(3,2)
x = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
y = [2.0d0, 4.0d0, 6.0d0, 8.0d0]
z(1,1) = 1.0d0
z(2,1) = 2.0d0
z(3,1) = 3.0d0
z(1,2) = 2.0d0
z(2,2) = 4.0d0
z(3,2) = 6.0d0
print *, mean(x)
print *, var(x)
print *, cov(x, y)
print *, corr(x, y)
print *, cov(z)
print *, corr(z)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(2.5)
    assert float(lines[1]) == pytest.approx(1.6666666666666667)
    assert float(lines[2]) == pytest.approx(3.3333333333333335)
    assert float(lines[3]) == pytest.approx(1.0)
    cov_values = [float(x) for x in lines[4].split()]
    corr_values = [float(x) for x in lines[5].split()]
    assert cov_values == pytest.approx([1.0, 2.0, 2.0, 4.0])
    assert corr_values == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_stdlib_stats_subset_supports_renaming(tmp_path):
    source = tmp_path / "xstdlib_stats_rename.f90"
    source.write_text(
        """
program main
use stdlib_stats, only: variance => var, cor => corr
implicit none
real(8) :: x(4), y(4)
x = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
y = [2.0d0, 4.0d0, 6.0d0, 8.0d0]
print *, variance(x)
print *, cor(x, y)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(1.6666666666666667)
    assert float(lines[1]) == pytest.approx(1.0)


def test_ofort_statistics_mod_median_moment_and_pca(tmp_path):
    source = tmp_path / "xofort_stats_pca.f90"
    source.write_text(
        """
program main
use ofort_statistics_mod, only: median, moment, pca, pca_transform, pca_inverse_transform
implicit none
real(8) :: x(4), z(4,2), components(2,2), singular_values(2), x_mean(2)
real(8) :: transformed(4,2), reconstructed(4,2)
x = [4.0d0, 1.0d0, 3.0d0, 2.0d0]
z(:,1) = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
z(:,2) = [2.0d0, 4.0d0, 6.0d0, 8.0d0]
print *, median(x)
print *, moment(x, 2)
call pca(z, components, singular_values, x_mean)
print *, singular_values
print *, x_mean
call pca_transform(z, components, transformed, x_mean)
call pca_inverse_transform(transformed, components, reconstructed, x_mean)
print *, reconstructed(1,1), reconstructed(4,2)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(2.5)
    assert float(lines[1]) == pytest.approx(1.25)
    singular_values = [float(x) for x in lines[2].split()]
    x_mean = [float(x) for x in lines[3].split()]
    reconstructed = [float(x) for x in lines[4].split()]
    assert singular_values[0] == pytest.approx(5.0)
    assert singular_values[1] == pytest.approx(0.0, abs=1.0e-10)
    assert x_mean == pytest.approx([2.5, 5.0])
    assert reconstructed == pytest.approx([1.0, 8.0])


def test_stdlib_stats_median_moment_and_pca(tmp_path):
    source = tmp_path / "xstdlib_stats_pca.f90"
    source.write_text(
        """
program main
use stdlib_stats, only: median, moment, pca, pca_transform, pca_inverse_transform
implicit none
real(8) :: x(3), z(3,2), components(1,2), singular_values(1), x_mean(2)
real(8) :: transformed(3,1), reconstructed(3,2)
x = [1.0d0, 5.0d0, 9.0d0]
z(:,1) = [1.0d0, 2.0d0, 3.0d0]
z(:,2) = [3.0d0, 6.0d0, 9.0d0]
print *, median(x)
print *, moment(x, 1, 0.0d0)
call pca(z, components, singular_values, x_mean)
call pca_transform(z, components, transformed, x_mean)
call pca_inverse_transform(transformed, components, reconstructed, x_mean)
print *, singular_values(1)
print *, x_mean
print *, reconstructed(1,1), reconstructed(3,2)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(5.0)
    assert float(lines[1]) == pytest.approx(5.0)
    assert float(lines[2]) == pytest.approx((20.0) ** 0.5)
    assert [float(x) for x in lines[3].split()] == pytest.approx([2.0, 6.0])
    assert [float(x) for x in lines[4].split()] == pytest.approx([1.0, 9.0])


def test_stdlib_stats_distribution_normal_subset(tmp_path):
    source = tmp_path / "xstdlib_normal.f90"
    source.write_text(
        """
program main
use stdlib_stats_distribution_normal, only: rvs_normal, pdf_normal, cdf_normal
implicit none
real(8) :: z, y(3), x
z = rvs_normal()
y = rvs_normal(loc=10.0d0, scale=2.0d0, array_size=3)
x = rvs_normal(10.0d0, 2.0d0)
print *, size(y)
print *, z == z, x == x
print *, pdf_normal(0.0d0, 0.0d0, 1.0d0)
print *, cdf_normal(0.0d0, 0.0d0, 1.0d0)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert int(lines[0]) == 3
    assert lines[1].split() == ["T", "T"]
    assert float(lines[2]) == pytest.approx(0.3989422804014327)
    assert float(lines[3]) == pytest.approx(0.5)


def test_stdlib_stats_distribution_normal_vector_pdf_cdf(tmp_path):
    source = tmp_path / "xstdlib_normal_vector.f90"
    source.write_text(
        """
program main
use stdlib_stats_distribution_normal, only: pdf_normal, cdf_normal
implicit none
real(8) :: x(3), mu(3), p(3), q(3)
x = [-1.0d0, 0.0d0, 1.0d0]
mu = [0.0d0, 0.0d0, 0.0d0]
p = pdf_normal(x, 0.0d0, 1.0d0)
q = cdf_normal(x, mu, 1.0d0)
print *, p
print *, q
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    p = [float(x) for x in result.stdout.splitlines()[0].split()]
    q = [float(x) for x in result.stdout.splitlines()[1].split()]
    assert p == pytest.approx([0.24197072451914337, 0.3989422804014327, 0.24197072451914337])
    assert q == pytest.approx([0.15865525393145707, 0.5, 0.8413447460685429])


def test_ofort_statistics_mod_calc_stats(tmp_path):
    source = tmp_path / "xcalc_stats.f90"
    source.write_text(
        """
program main
use ofort_statistics_mod, only: calc_stats
implicit none
real(8) :: x(4)
real(8) :: xm, xs, xv
real(8) :: xm2, xv2
x = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
call calc_stats(x, mean=xm, sd=xs, var=xv)
call calc_stats(x, xm2, var=xv2)
print *, xm
print *, xs
print *, xv
print *, xm2
print *, xv2
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert float(lines[0]) == pytest.approx(2.5)
    assert float(lines[1]) == pytest.approx(1.2909944487358056)
    assert float(lines[2]) == pytest.approx(1.6666666666666667)
    assert float(lines[3]) == pytest.approx(2.5)
    assert float(lines[4]) == pytest.approx(1.6666666666666667)


def test_ofort_statistics_mod_calc_col_stats(tmp_path):
    source = tmp_path / "xcalc_col_stats.f90"
    source.write_text(
        """
program main
use ofort_statistics_mod, only: calc_col_stats, cov, cor
implicit none
real(8) :: x(3,2)
real(8) :: mu(2), xs(2), xv(2), c(2,2), r(2,2)
real(8) :: rms(2), c_zm(2,2), r_zm(2,2)
x(1,1) = 1.0d0
x(2,1) = 2.0d0
x(3,1) = 3.0d0
x(1,2) = 2.0d0
x(2,2) = 4.0d0
x(3,2) = 6.0d0
call calc_col_stats(x, mean=mu, sd=xs, var=xv, cov=c, corr=r, rms=rms, cov_zm=c_zm, corr_zm=r_zm)
print *, mu
print *, xs
print *, xv
print *, c
print *, r
print *, rms
print *, c_zm
print *, r_zm
print *, cov(x)
print *, cor(x)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:2] == pytest.approx([2.0, 4.0])
    assert vals[2:4] == pytest.approx([1.0, 2.0])
    assert vals[4:6] == pytest.approx([1.0, 4.0])
    assert vals[6:10] == pytest.approx([1.0, 2.0, 2.0, 4.0])
    assert vals[10:14] == pytest.approx([1.0, 1.0, 1.0, 1.0])
    assert vals[14:16] == pytest.approx([(14.0 / 3.0) ** 0.5, (56.0 / 3.0) ** 0.5])
    assert vals[16:20] == pytest.approx([14.0 / 3.0, 28.0 / 3.0, 28.0 / 3.0, 56.0 / 3.0])
    assert vals[20:24] == pytest.approx([1.0, 1.0, 1.0, 1.0])
    assert vals[24:28] == pytest.approx([1.0, 2.0, 2.0, 4.0])
    assert vals[28:32] == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_ofort_la_mod_initial_functions(tmp_path):
    source = tmp_path / "xofort_la_mod.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: matmul2, transpose2, crossprod, tcrossprod, center_cols, col_sums, col_means
implicit none
real(8) :: a(2,2), b(2,2), mu(2), centered(2,2)
a(1,1) = 1.0d0
a(2,1) = 2.0d0
a(1,2) = 3.0d0
a(2,2) = 4.0d0
b(1,1) = 5.0d0
b(2,1) = 6.0d0
b(1,2) = 7.0d0
b(2,2) = 8.0d0
mu = col_means(a)
call center_cols(a, mu, centered)
print *, col_sums(a)
print *, mu
print *, transpose2(a)
print *, matmul2(a, b)
print *, crossprod(a)
print *, tcrossprod(a)
print *, centered
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:2] == pytest.approx([3.0, 7.0])
    assert vals[2:4] == pytest.approx([1.5, 3.5])
    assert vals[4:8] == pytest.approx([1.0, 3.0, 2.0, 4.0])
    assert vals[8:12] == pytest.approx([23.0, 34.0, 31.0, 46.0])
    assert vals[12:16] == pytest.approx([5.0, 11.0, 11.0, 25.0])
    assert vals[16:20] == pytest.approx([10.0, 14.0, 14.0, 20.0])
    assert vals[20:24] == pytest.approx([-0.5, 0.5, -0.5, 0.5])


def test_ofort_la_mod_stdlib_linalg_helpers(tmp_path):
    source = tmp_path / "xofort_linalg_helpers.f90"
    source.write_text(
        """
program main
use ofort_la_mod, only: eye, diag, trace, outer_product, is_square, is_diagonal, is_symmetric
use stdlib_linalg, only: std_eye => eye, std_diag => diag, std_trace => trace, &
    std_outer_product => outer_product, std_is_square => is_square, &
    std_is_diagonal => is_diagonal, std_is_symmetric => is_symmetric
implicit none
real(8) :: a(2,2), v(3), w(2)
a(1,1) = 1.0d0
a(2,1) = 2.0d0
a(1,2) = 2.0d0
a(2,2) = 4.0d0
v = [1.0d0, 2.0d0, 3.0d0]
w = [10.0d0, 20.0d0]
print *, eye(2)
print *, eye(2, 3)
print *, diag(v)
print *, diag(diag(v))
print *, diag(a, 1)
print *, trace(a)
print *, outer_product(v, w)
print *, is_square(a), is_diagonal(diag(v)), is_diagonal(a), is_symmetric(a)
print *, std_eye(2)
print *, std_diag(v)
print *, std_trace(a)
print *, std_outer_product(w, w)
print *, std_is_square(a), std_is_diagonal(std_diag(w)), std_is_symmetric(a)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    tokens = result.stdout.split()
    vals = [float(x) for x in tokens if x not in ("T", "F")]
    bools = [x for x in tokens if x in ("T", "F")]
    assert vals[0:4] == pytest.approx([1.0, 0.0, 0.0, 1.0])
    assert vals[4:10] == pytest.approx([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])
    assert vals[10:19] == pytest.approx([1.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 3.0])
    assert vals[19:22] == pytest.approx([1.0, 2.0, 3.0])
    assert vals[22:23] == pytest.approx([2.0])
    assert vals[23:24] == pytest.approx([5.0])
    assert vals[24:30] == pytest.approx([10.0, 20.0, 30.0, 20.0, 40.0, 60.0])
    assert bools[0:4] == ["T", "T", "F", "T"]
    assert vals[30:34] == pytest.approx([1.0, 0.0, 0.0, 1.0])
    assert vals[34:43] == pytest.approx([1.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 3.0])
    assert vals[43:44] == pytest.approx([5.0])
    assert vals[44:48] == pytest.approx([100.0, 200.0, 200.0, 400.0])
    assert bools[4:7] == ["T", "T", "T"]


def test_ofort_io_mod_read_matrix_and_vector(tmp_path):
    matrix_file = tmp_path / "matrix.txt"
    matrix_file.write_text(
        """
# comment
1 2 3
4 5 6
""".lstrip(),
        encoding="utf-8",
    )
    prices_file = tmp_path / "prices.csv"
    prices_file.write_text(
        """
date,SPY,TLT
2024-01-02,472.65,97.12
2024-01-03,468.79,98.04
""".lstrip(),
        encoding="utf-8",
    )
    vector_file = tmp_path / "vector.txt"
    vector_file.write_text("10\n20 30\n", encoding="utf-8")
    matrix_path = str(matrix_file).replace("\\", "/")
    prices_path = str(prices_file).replace("\\", "/")
    vector_path = str(vector_file).replace("\\", "/")

    source = tmp_path / "xofort_io_mod.f90"
    source.write_text(
        f"""
program main
use ofort_io_mod, only: read_matrix, read_vector
implicit none
real(8), allocatable :: a(:,:), prices(:,:), v(:)
character(len=20), allocatable :: dates(:)
call read_matrix("{matrix_path}", a)
call read_matrix("{prices_path}", prices, delimiter=",", header=.true., ncol=2, row_labels=dates)
call read_vector("{vector_path}", v)
print *, size(a, 1), size(a, 2)
print *, a
print *, size(prices, 1), size(prices, 2)
print *, trim(dates(1)), trim(dates(2))
print *, prices
print *, size(v)
print *, v
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "2024-01-02" in result.stdout
    assert "2024-01-03" in result.stdout
    numeric_stdout = result.stdout.replace("2024-01-02", "").replace("2024-01-03", "")
    vals = [float(x) for x in numeric_stdout.split()]
    assert vals[0:2] == pytest.approx([2.0, 3.0])
    assert vals[2:8] == pytest.approx([1.0, 4.0, 2.0, 5.0, 3.0, 6.0])
    assert vals[8:10] == pytest.approx([2.0, 2.0])
    assert vals[10:14] == pytest.approx([472.65, 468.79, 97.12, 98.04])
    assert vals[14:18] == pytest.approx([3.0, 10.0, 20.0, 30.0])


def test_stdlib_io_loadtxt_subset(tmp_path):
    data_file = tmp_path / "data.csv"
    data_file.write_text(
        """
skip me
1,2,3
4,5,6
7,8,9
""".lstrip(),
        encoding="utf-8",
    )
    data_path = str(data_file).replace("\\", "/")
    source = tmp_path / "xstdlib_io.f90"
    source.write_text(
        f"""
program main
use stdlib_io, only: loadtxt
implicit none
real(8), allocatable :: a(:,:), b(:,:)
call loadtxt("{data_path}", a, skiprows=1, max_rows=2, delimiter=",")
call loadtxt("{data_path}", b, 1, 1, "*", ",")
print *, size(a, 1), size(a, 2)
print *, a
print *, size(b, 1), size(b, 2)
print *, b
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:2] == pytest.approx([2.0, 3.0])
    assert vals[2:8] == pytest.approx([1.0, 4.0, 2.0, 5.0, 3.0, 6.0])
    assert vals[8:10] == pytest.approx([1.0, 3.0])
    assert vals[10:13] == pytest.approx([1.0, 2.0, 3.0])


def test_stdlib_io_savetxt_subset(tmp_path):
    out_file = tmp_path / "saved.csv"
    out_path = str(out_file).replace("\\", "/")
    source = tmp_path / "xstdlib_io_savetxt.f90"
    source.write_text(
        f"""
program main
use stdlib_io, only: savetxt, loadtxt
implicit none
real(8) :: a(2,3)
real(8), allocatable :: b(:,:)
a(1,1) = 1.0d0
a(2,1) = 4.0d0
a(1,2) = 2.0d0
a(2,2) = 5.0d0
a(1,3) = 3.0d0
a(2,3) = 6.0d0
call savetxt("{out_path}", a, delimiter=",", header="c1,c2,c3", comments="")
call loadtxt("{out_path}", b, skiprows=1, delimiter=",")
print *, size(b, 1), size(b, 2)
print *, b
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    vals = [float(x) for x in result.stdout.split()]
    assert vals[0:2] == pytest.approx([2.0, 3.0])
    assert vals[2:8] == pytest.approx([1.0, 4.0, 2.0, 5.0, 3.0, 6.0])
    assert out_file.read_text(encoding="utf-8").splitlines()[0] == "c1,c2,c3"


def test_random_number_accepts_array_section_harvest(tmp_path):
    source = tmp_path / "xrandom_number_section.f90"
    source.write_text(
        """
program main
implicit none
integer :: m
real(8) :: u(5)
m = 3
u = -1.0d0
call random_number(u(1:m))
print *, u(4), u(5)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "-1.0 -1.0\n"


def test_random_number_accepts_array_element_harvest(tmp_path):
    source = tmp_path / "xrandom_number_element.f90"
    source.write_text(
        """
program main
implicit none
real(8) :: u(2)
u = -1.0d0
call random_number(u(1))
print *, u(1) >= 0.0d0 .and. u(1) < 1.0d0, u(2)
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "T -1.0\n"


def test_ofort_random_mod_rnorm_fill(tmp_path):
    source = tmp_path / "xrnorm_fill.f90"
    source.write_text(
        """
program main
use ofort_random_mod, only: rnorm, rnorm_fill
use ofort_statistics_mod, only: variance
implicit none
real(8) :: x(1000), y(1000), z(20, 10)
x = 0.0d0
call rnorm_fill(x, 1)
call rnorm_fill(y, 2)
call rnorm_fill(z)
print *, variance(x) > 0.0d0
print *, variance(y) > 0.0d0
print *, variance(rnorm(1000, 2)) > 0.0d0
print *, variance(reshape(z, [200])) > 0.0d0
end program main
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "T\nT\nT\nT\n"


def test_ofort_random_mod_distribution_variates(tmp_path):
    source = tmp_path / "xrandom_dist.f90"
    source.write_text(
        """
program xrandom_dist
use ofort_random_mod, only: randn, normrnd, unifrnd, exprnd, lognrnd, gamrnd, &
    poissrnd, binornd, trnd, laprnd, sechrnd, logisticrnd
implicit none
real(kind=8), allocatable :: x(:), a(:,:)
print *, randn() == randn()
x = randn(4)
a = normrnd(10.0d0, 2.0d0, 2, 3)
print *, size(x), shape(a)
print *, all(unifrnd(2.0d0, 3.0d0, 20) >= 2.0d0), all(unifrnd(2.0d0, 3.0d0, 20) <= 3.0d0)
print *, all(exprnd(2.0d0, 20) >= 0.0d0), all(lognrnd(0.0d0, 1.0d0, 20) >= 0.0d0)
print *, all(gamrnd(2.0d0, 1.0d0, 20) >= 0.0d0), all(poissrnd(3.0d0, 20) >= 0.0d0)
print *, all(binornd(5.0d0, 0.5d0, 20) >= 0.0d0), all(binornd(5.0d0, 0.5d0, 20) <= 5.0d0)
print *, size(trnd(5.0d0, 3)), size(laprnd(0.0d0, 1.0d0, 3)), size(sechrnd(0.0d0, 1.0d0, 3)), size(logisticrnd(0.0d0, 1.0d0, 3))
end program xrandom_dist
""".lstrip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = [line.split() for line in result.stdout.splitlines()]
    assert lines[1] == ["4", "2", "3"]
    assert lines[2] == ["T", "T"]
    assert lines[3] == ["T", "T"]
    assert lines[4] == ["T", "T"]
    assert lines[5] == ["T", "T"]
    assert lines[6] == ["3", "3", "3", "3"]


def test_write_and_read_external_file(tmp_path):
    source = CASES / "xwrite_file.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10 20 30\nsum(abs(i-ichk)) =  0\n"
    assert (tmp_path / "temp.txt").read_text(encoding="utf-8") == "10 20 30\n"


def test_write_read_internal_file_and_allocatable(tmp_path):
    source = CASES / "xwrite_file_alloc.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10.1 20.1 30.1\nsum(abs(i-ichk)) =  0.0\n"
    assert (tmp_path / "temp.txt").read_text(encoding="utf-8") == "3 10.1 20.1 30.1\n"


def test_unformatted_stream_io(tmp_path):
    source = CASES / "xstream.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10.1 20.1 30.1\nsum(abs(i-ichk)) =  0.0\n"
    assert (tmp_path / "temp.bin").stat().st_size == 28


def test_exit_from_unbounded_do_loop():
    source = CASES / "xexit.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines
    assert lines[-1].startswith("big ")
    assert float(lines[-1].split()[1]) > 0.9
    for line in lines[:-1]:
        assert 0.0 <= float(line) <= 0.9


def test_check_parses_without_running(tmp_path):
    source = tmp_path / "xcheck.f90"
    source.write_text(
        "program xcheck\n"
        "print *, 12345\n"
        "end program xcheck\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_check_rejects_syntax_error(tmp_path):
    source = tmp_path / "xbad.f90"
    source.write_text(
        "program xbad\n"
        "print *, (1\n"
        "end program xbad\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""


def test_check_skips_generic_interface_block(tmp_path):
    source = tmp_path / "xinterface.f90"
    source.write_text(
        "module m\n"
        "interface g\n"
        "  module procedure s\n"
        "end interface g\n"
        "contains\n"
        "subroutine s()\n"
        "end subroutine s\n"
        "end module m\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_check_accepts_utf8_bom(tmp_path):
    source = tmp_path / "xbom.f90"
    source.write_bytes(
        b"\xef\xbb\xbfprogram xbom\n"
        b"print *, 1\n"
        b"end program xbom\n"
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_dep_resolves_modules_from_main_directory(tmp_path):
    main = tmp_path / "main.f90"
    mod = tmp_path / "m_mod.f90"
    helper = tmp_path / "helper_module.f90"

    main.write_text(
        "program main\n"
        "use m\n"
        "print *, answer()\n"
        "end program main\n",
        encoding="utf-8",
    )
    mod.write_text(
        "module m\n"
        "use helper, only: base\n"
        "contains\n"
        "integer function answer()\n"
        "answer = base + 2\n"
        "end function answer\n"
        "end module m\n",
        encoding="utf-8",
    )
    helper.write_text(
        "module helper\n"
        "integer, parameter :: base = 40\n"
        "end module helper\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "42\n"


def test_dep_check_gfortran_uses_resolved_file_list(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    main = tmp_path / "main.f90"
    mod = tmp_path / "m.f90"

    main.write_text(
        "program main\n"
        "use m\n"
        "call say()\n"
        "end program main\n",
        encoding="utf-8",
    )
    mod.write_text(
        "module m\n"
        "contains\n"
        "subroutine say()\n"
        "print '(a)', 'dep-ok'\n"
        "end subroutine say\n"
        "end module m\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main), "--check-gfortran"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "dep-ok\nofort output matches gfortran\n"


def test_dep_reports_missing_module(tmp_path):
    main = tmp_path / "main.f90"
    main.write_text(
        "program main\n"
        "use missing_mod\n"
        "print *, 1\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--dep: module 'missing_mod' not found" in result.stderr
    assert "missing_mod.f90" in result.stderr
    assert "missing_mod_mod.f90" in result.stderr
    assert "missing_mod_module.f90" in result.stderr


def test_dep_strips_mod_suffix_for_module_file_stem(tmp_path):
    main = tmp_path / "main.f90"
    mod = tmp_path / "kind.f90"

    main.write_text(
        "program main\n"
        "use kind_mod\n"
        "print *, ik\n"
        "end program main\n",
        encoding="utf-8",
    )
    mod.write_text(
        "module kind_mod\n"
        "integer, parameter :: ik = 8\n"
        "end module kind_mod\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "8\n"


def test_dep_skips_iso_fortran_env_builtin(tmp_path):
    main = tmp_path / "main.f90"

    main.write_text(
        "program main\n"
        "use iso_fortran_env\n"
        "integer :: i\n"
        "i = 12\n"
        "print *, i\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "12\n"


def test_unsupported_iso_fortran_env_real_kind_is_rejected(tmp_path):
    source = tmp_path / "xreal128.f90"
    source.write_text(
        "use iso_fortran_env, only: real128\n"
        "implicit none\n"
        "real(kind=real128) :: x\n"
        "print *, huge(x)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "Unsupported REAL kind -1" in result.stderr


def test_dep_skips_common_intrinsic_modules(tmp_path):
    main = tmp_path / "main.f90"

    main.write_text(
        "program main\n"
        "use iso_c_binding\n"
        "use ieee_arithmetic\n"
        "use ieee_exceptions\n"
        "use ieee_features\n"
        "print *, 7\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "7\n"


def test_typed_function_prefixes():
    source = CASES / "xtyped_function.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "6.0\n7.5\n"


def test_type_keyword_intrinsic_call():
    source = CASES / "xtype_keyword_intrinsic.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "3.0 4.0\n"


def test_batch_runner_runs_file_glob(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "==> " in result.stdout
    assert "a.f90" in result.stdout
    assert "b.f90" in result.stdout
    assert "(2 lines)" in result.stdout
    assert "\n\n==> " in result.stdout
    assert "11" in result.stdout
    assert "22" in result.stdout
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_forwards_check(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--check", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("ofort check passed") == 2
    output_lines = result.stdout.splitlines()
    assert "11" not in output_lines
    assert "22" not in output_lines
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_limit(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--limit", "2", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "22" in output_lines
    assert "33" not in output_lines
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_skip_lines_skips_expanded_inputs(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--skip-lines", "1", "--limit", "1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output_lines = result.stdout.splitlines()
    assert "11" not in output_lines
    assert "22" in output_lines
    assert "33" not in output_lines
    assert re.search(r"1 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_expands_at_file_list(tmp_path):
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (subdir / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    manifest = tmp_path / "xfiles.txt"
    manifest.write_text(
        "# relative paths are resolved from this file\n"
        "\n"
        "src/a.f90\n"
        "src/b.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--dep", "--fast", f"@{manifest}", "--timeout", "30", "--max-fail", "1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "22" in output_lines
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_runs_manifest_files_as_complete_programs(tmp_path):
    program_dir = tmp_path / "prog"
    program_dir.mkdir()
    (program_dir / "m.f90").write_text(
        "module m\n"
        "contains\n"
        "integer function value()\n"
        "value = 42\n"
        "end function\n"
        "end module\n",
        encoding="utf-8",
    )
    (program_dir / "xmain.f90").write_text(
        "program main\n"
        "use m\n"
        "print *, value()\n"
        "end program\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "xfiles.txt"
    manifest.write_text(
        f"{program_dir / 'm.f90'}\n"
        f"{program_dir / 'xmain.f90'}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--manifests", "--dep", "--fast", str(tmp_path / "*files.txt")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "xfiles.txt" in result.stdout
    assert "m.f90" not in result.stdout
    assert "xmain.f90" not in result.stdout
    assert "42" in result.stdout.splitlines()
    assert re.search(r"1 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_check_gfortran_classifies_ofort_manifest_failures(tmp_path):
    checker = tmp_path / "fake_gfortran.py"
    fake_ofort = tmp_path / "fake_ofort.bat"
    checker.write_text(
        "import pathlib\n"
        "import sys\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg == '-fsyntax-only':\n"
        "        continue\n"
        "    if 'bad' in pathlib.Path(arg).name:\n"
        "        raise SystemExit(1)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake_ofort.write_text(
        "@echo off\n"
        "echo ofort tried %~nx1\n"
        "exit /b 1\n",
        encoding="utf-8",
    )
    for stem in ["bad", "good1", "good2"]:
        program_dir = tmp_path / stem
        program_dir.mkdir()
        source = program_dir / f"{stem}.f90"
        source.write_text("print *, 11\nend\n", encoding="utf-8")
        manifest = tmp_path / f"{stem}_files.txt"
        manifest.write_text(str(source) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--manifests",
            "--check-gfortran",
            "--gfortran",
            f'"{sys.executable}" "{checker}"',
            "--ofort",
            str(fake_ofort),
            "--timeout",
            "5",
            "--max-fail",
            "1",
            str(tmp_path / "*_files.txt"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        # This launches the runner, batch files, and Python compiler checkers.
        # Allow startup headroom while bounding each child with --timeout.
        timeout=30,
    )

    assert result.returncode == 1
    assert "bad_files.txt" in result.stdout
    assert "ofort tried bad.f90" in result.stdout
    assert "ofort tried good1.f90" in result.stdout
    assert "ofort tried good2.f90" not in result.stdout
    assert "stopped after 1 failures; 1 sources not processed" in result.stderr
    assert re.search(r"1 of 3 failed, 1 skipped in \d+\.\d{2}s", result.stderr)


def test_batch_runner_run_dir_source_resolves_input_files(tmp_path):
    program_dir = tmp_path / "prog"
    program_dir.mkdir()
    (program_dir / "input.txt").write_text("17\n", encoding="utf-8")
    source = program_dir / "xread.f90"
    source.write_text(
        "integer :: x\n"
        "open(10, file='input.txt', status='old')\n"
        "read(10, *) x\n"
        "close(10)\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--run-dir", "source", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "17" in result.stdout.splitlines()


def test_batch_runner_run_dir_manifest_resolves_input_files(tmp_path):
    program_dir = tmp_path / "prog"
    program_dir.mkdir()
    (program_dir / "input.txt").write_text("23\n", encoding="utf-8")
    (program_dir / "xread.f90").write_text(
        "integer :: x\n"
        "open(10, file='input.txt', status='old')\n"
        "read(10, *) x\n"
        "close(10)\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )
    manifest = program_dir / "xfiles.txt"
    manifest.write_text("xread.f90\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--manifests", "--run-dir", "manifest", str(manifest)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "23" in result.stdout.splitlines()


def test_batch_runner_max_lines_skips_long_files(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text(
        "print *, 22\n"
        "print *, 33\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--max-lines", "2", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "a.f90" in result.stdout
    assert "(2 lines)" in result.stdout
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "b.f90" not in result.stdout
    assert "22" not in output_lines
    assert "(3 lines)" not in result.stdout
    assert "skipped: longer than 2 lines" not in result.stdout
    assert re.search(r"1 passed, 1 skipped in \d+\.\d{2}s", result.stdout)


def test_batch_runner_quiet_suppresses_success_output(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--quiet", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_batch_runner_filter_skips_rejected_files(tmp_path):
    good = tmp_path / "good.f90"
    bad = tmp_path / "bad.f90"
    filter_script = tmp_path / "filter.py"
    good.write_text("print *, 11\nend\n", encoding="utf-8")
    bad.write_text("print *, 22\nend\n", encoding="utf-8")
    filter_script.write_text(
        "import pathlib\n"
        "import sys\n"
        "raise SystemExit(0 if pathlib.Path(sys.argv[-1]).name == 'good.f90' else 1)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--filter",
            f'"{sys.executable}" "{filter_script}"',
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "good.f90" in result.stdout
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "bad.f90" not in result.stdout
    assert "22" not in output_lines
    assert re.search(r"1 passed, 1 skipped in \d+\.\d{2}s", result.stdout)


def test_batch_runner_quiet_prints_failed_files(tmp_path):
    good = tmp_path / "good.f90"
    bad = tmp_path / "bad.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    good.write_text("print *, 11\nend\n", encoding="utf-8")
    bad.write_text("print *, 22\nend\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        "echo handled %~nx1\n"
        "echo problem %~nx1 1>&2\n"
        "if /I \"%~nx1\"==\"bad.f90\" exit /b 1\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--quiet",
            "--ofort",
            str(fake_ofort),
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "bad.f90" in result.stdout
    assert "handled bad.f90" in result.stdout
    assert "good.f90" not in result.stdout
    assert "handled good.f90" not in result.stdout
    assert "problem bad.f90" in result.stderr
    assert "problem good.f90" not in result.stderr
    assert re.search(r"1 of 2 failed in \d+\.\d{2}s", result.stderr)


def test_batch_runner_rejects_bad_limit(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--limit", "0", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--limit must be at least 1" in result.stderr


def test_batch_runner_rejects_negative_skip_lines(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--skip-lines", "-1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--skip-lines must be non-negative" in result.stderr


def test_use_only_imported_procedure_wins_over_same_name_in_other_module(tmp_path):
    source = tmp_path / "xuse_only_proc_collision.f90"
    source.write_text(
        "module m1\n"
        "contains\n"
        "subroutine s(a, b, c)\n"
        "real :: a(:), b(:), c(:)\n"
        "print *, size(c)\n"
        "end subroutine\n"
        "end module\n"
        "module m2\n"
        "contains\n"
        "subroutine s(x, n, k)\n"
        "real :: x(:)\n"
        "integer :: n, k\n"
        "print *, n + k\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m1, only: dummy => s\n"
        "use m2, only: s\n"
        "real :: x(2)\n"
        "x = 1.0\n"
        "call s(x, 2, 3)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["5"]


def test_use_only_imported_generic_resolves_private_module_procedures(tmp_path):
    source = tmp_path / "xuse_only_generic_private.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: g\n"
        "interface g\n"
        "module procedure g_int, g_real\n"
        "end interface\n"
        "contains\n"
        "integer function g_int(i)\n"
        "integer, intent(in) :: i\n"
        "g_int = i + 10\n"
        "end function\n"
        "real function g_real(x)\n"
        "real, intent(in) :: x\n"
        "g_real = x + 20.0\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m, only: g\n"
        "print *, g(3), g(4.0)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["13", "24.0"]


def test_generic_resolution_uses_declared_type_of_absent_optional_actual(tmp_path):
    source = tmp_path / "xoptional_generic_actual.f90"
    source.write_text(
        "module defaults\n"
        "implicit none\n"
        "private\n"
        "public :: default\n"
        "interface default\n"
        "module procedure default_integer, default_real\n"
        "end interface\n"
        "contains\n"
        "integer function default_integer(def, opt)\n"
        "integer, intent(in) :: def\n"
        "integer, intent(in), optional :: opt\n"
        "if (present(opt)) then\n"
        "   default_integer = opt\n"
        "else\n"
        "   default_integer = def\n"
        "end if\n"
        "end function\n"
        "real(kind=kind(1.0d0)) function default_real(def, opt)\n"
        "real(kind=kind(1.0d0)), intent(in) :: def\n"
        "real(kind=kind(1.0d0)), intent(in), optional :: opt\n"
        "if (present(opt)) then\n"
        "   default_real = opt\n"
        "else\n"
        "   default_real = def\n"
        "end if\n"
        "end function\n"
        "end module\n"
        "module user_mod\n"
        "use defaults, only: default\n"
        "implicit none\n"
        "private\n"
        "public :: show, show_prob\n"
        "contains\n"
        "subroutine show(outu)\n"
        "integer, intent(in), optional :: outu\n"
        "print *, default(outu, 6)\n"
        "end subroutine\n"
        "subroutine show_prob(prob)\n"
        "real(kind=kind(1.0d0)), intent(in), optional :: prob\n"
        "print *, default(1.0d0, prob)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use user_mod, only: show, show_prob\n"
        "call show()\n"
        "call show(9)\n"
        "call show_prob(0.6d0)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["6", "6", "0.6"]


def test_generic_resolution_rejects_missing_real_specific(tmp_path):
    source = tmp_path / "xgeneric_no_real_specific.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "interface g\n"
        "module procedure g_int\n"
        "end interface\n"
        "contains\n"
        "integer function g_int(i)\n"
        "integer, intent(in) :: i\n"
        "g_int = i + 1\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m, only: g\n"
        "print *, g(1.5)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "No matching specific procedure for generic 'g'" in result.stderr


def test_generic_resolution_rejects_double_actual_for_default_real_specific(tmp_path):
    source = tmp_path / "xgeneric_default_real_no_double.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "interface twice\n"
        "module procedure twice_real\n"
        "end interface\n"
        "contains\n"
        "real function twice_real(x)\n"
        "real, intent(in) :: x\n"
        "twice_real = 2*x\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m, only: twice\n"
        "print *, twice(1.0d0)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "No matching specific procedure for generic 'twice'" in result.stderr


def test_generic_resolution_uses_integer_literal_kind_parameters(tmp_path):
    source = tmp_path / "xgeneric_integer_kind_params.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: i32 = selected_int_kind(9)\n"
        "integer, parameter :: i64 = selected_int_kind(18)\n"
        "interface twice\n"
        "module procedure twice_i32, twice_i64\n"
        "end interface\n"
        "contains\n"
        "integer(i32) function twice_i32(x)\n"
        "integer(i32), intent(in) :: x\n"
        "twice_i32 = 2*x\n"
        "end function\n"
        "integer(i64) function twice_i64(x)\n"
        "integer(i64), intent(in) :: x\n"
        "twice_i64 = 2*x\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "print *, kind(1_i32), kind(1_i64)\n"
        "print *, kind(twice(1_i32)), kind(twice(1_i64))\n"
        "print *, twice(3_i32), twice(3_i64)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["4", "8", "4", "8", "6", "6"]


def test_generic_resolution_uses_allocatable_array_declared_kind(tmp_path):
    source = tmp_path / "xgeneric_allocatable_real_kind.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "interface sort\n"
        "module procedure sort_real_dp, sort_int\n"
        "end interface\n"
        "contains\n"
        "subroutine sort_real_dp(x)\n"
        "real(kind=dp), intent(inout) :: x(:)\n"
        "x = x + 1.0_dp\n"
        "end subroutine\n"
        "subroutine sort_int(i)\n"
        "integer, intent(inout) :: i(:)\n"
        "i = i + 10\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m, only: dp, sort\n"
        "implicit none\n"
        "real(kind=dp), allocatable :: x(:)\n"
        "allocate(x(2))\n"
        "x = [1.0_dp, 2.0_dp]\n"
        "call sort(x)\n"
        "print *, kind(x), x\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["8", "2.0", "3.0"]


def test_generic_resolution_uses_array_section_source_kind(tmp_path):
    source = tmp_path / "xsection_generic_kind.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "interface set_alloc\n"
        "module procedure set_alloc_real_matrix\n"
        "end interface\n"
        "contains\n"
        "function true_pos(mask) result(idx)\n"
        "logical, intent(in) :: mask(:)\n"
        "integer, allocatable :: idx(:)\n"
        "integer :: i\n"
        "idx = pack([(i, i=1,size(mask))], mask)\n"
        "end function\n"
        "subroutine set_alloc_real_matrix(x, y)\n"
        "real(kind=dp), intent(in) :: x(:,:)\n"
        "real(kind=dp), allocatable, intent(out) :: y(:,:)\n"
        "allocate(y(size(x,1), size(x,2)))\n"
        "y = x\n"
        "end subroutine\n"
        "subroutine filter(x)\n"
        "real(kind=dp), allocatable, intent(inout) :: x(:,:)\n"
        "logical :: keep(size(x,1))\n"
        "keep = [.true., .false., .true.]\n"
        "call set_alloc((x(true_pos(keep),:)), x)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "real(kind=dp), allocatable :: x(:,:)\n"
        "allocate(x(3,2))\n"
        "x = reshape([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp, 5.0_dp, 6.0_dp], shape(x))\n"
        "call filter(x)\n"
        "print *, shape(x), x\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "2", "1.0", "3.0", "4.0", "6.0"]


def test_generic_resolution_uses_intent_out_allocatable_array_declared_kind(tmp_path):
    source = tmp_path / "xgeneric_intent_out_alloc_kind.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "interface set_alloc\n"
        "module procedure set_alloc_integer_matrix\n"
        "end interface\n"
        "integer, allocatable :: store(:,:)\n"
        "contains\n"
        "subroutine set_alloc_integer_matrix(x, y)\n"
        "integer, intent(in) :: x(:,:)\n"
        "integer, allocatable, intent(out) :: y(:,:)\n"
        "allocate(y(size(x,1), size(x,2)))\n"
        "y = x\n"
        "end subroutine\n"
        "subroutine fill()\n"
        "if (allocated(store)) deallocate(store)\n"
        "allocate(store(2,2))\n"
        "store = reshape([1, 2, 3, 4], shape(store))\n"
        "end subroutine\n"
        "subroutine get_copy(out)\n"
        "integer, allocatable, intent(out) :: out(:,:)\n"
        "call fill()\n"
        "call set_alloc(store, out)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, allocatable :: a(:,:)\n"
        "call get_copy(a)\n"
        "print *, shape(a), a\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "2", "1", "2", "3", "4"]


def test_scalar_assignment_to_real_array_preserves_generic_element_type(tmp_path):
    source = tmp_path / "xgeneric_reshape_real_array_ctor.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "interface s\n"
        "module procedure s_real\n"
        "end interface\n"
        "contains\n"
        "subroutine s_real(x)\n"
        "real(kind=dp), intent(in) :: x(:,:)\n"
        "print *, shape(x), kind(x), x\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, parameter :: n = 3\n"
        "real(kind=dp) :: ytrue(n), trend(n), yy(n)\n"
        "integer :: i\n"
        "do i = 1, n\n"
        "   ytrue(i) = 1\n"
        "   trend(i) = 2\n"
        "   yy(i) = 3\n"
        "end do\n"
        "call s(reshape([ytrue, trend, yy], [n, 3]))\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["3", "3", "8", "1.0", "1.0", "1.0", "2.0", "2.0", "2.0", "3.0", "3.0", "3.0"]


def test_real_implied_do_expression_preserves_generic_element_type(tmp_path):
    source = tmp_path / "xgeneric_implied_do_real_expr.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "interface s\n"
        "module procedure s_real\n"
        "end interface\n"
        "contains\n"
        "subroutine wrapper(y)\n"
        "real(kind=dp), intent(in) :: y(:,:)\n"
        "integer :: i\n"
        "call s(1.0_dp*(/(i,i=1,size(y,1))/), y)\n"
        "end subroutine\n"
        "subroutine s_real(x, y)\n"
        "real(kind=dp), intent(in) :: x(:)\n"
        "real(kind=dp), intent(in) :: y(:,:)\n"
        "print *, kind(x), kind(x(1)), size(x), shape(y)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "real(kind=dp) :: y(2,3)\n"
        "y = 2\n"
        "call wrapper(y)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["8", "8", "2", "2", "3"]


def test_generic_interface_rejects_ambiguous_specifics(tmp_path):
    source = tmp_path / "xambiguous_generic.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: i32 = selected_int_kind(9)\n"
        "integer, parameter :: i64 = selected_int_kind(18)\n"
        "interface twice\n"
        "module procedure twice_i32, twice_i64\n"
        "end interface\n"
        "contains\n"
        "integer(i32) function twice_i32(x)\n"
        "integer, intent(in) :: x\n"
        "twice_i32 = 2*x\n"
        "end function\n"
        "integer(i64) function twice_i64(x)\n"
        "integer, intent(in) :: x\n"
        "twice_i64 = 2*x\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "print *, twice(1)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Ambiguous interfaces in generic interface 'twice'" in result.stderr
    assert "twice_i32" in result.stderr
    assert "twice_i64" in result.stderr


def test_generic_interface_distinguishes_derived_dummy_types(tmp_path):
    source = tmp_path / "xgeneric_derived_dummy_types.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type date_mdy\n"
        "integer :: i\n"
        "end type\n"
        "type time_of_day\n"
        "integer :: i\n"
        "end type\n"
        "interface within\n"
        "module procedure date_within, time_within\n"
        "end interface\n"
        "contains\n"
        "logical function date_within(xdate,d1,d2) result(tf)\n"
        "type(date_mdy), intent(in) :: xdate,d1,d2\n"
        "tf = xdate%i >= d1%i .and. xdate%i <= d2%i\n"
        "end function\n"
        "logical function time_within(xtime,t1,t2) result(tf)\n"
        "type(time_of_day), intent(in) :: xtime,t1,t2\n"
        "tf = xtime%i >= t1%i .and. xtime%i <= t2%i\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "print *, within(date_mdy(2), date_mdy(1), date_mdy(3))\n"
        "print *, within(time_of_day(5), time_of_day(1), time_of_day(3))\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T", "F"]


def test_imported_module_variable_assignment_is_visible_to_module_procedure(tmp_path):
    source = tmp_path / "ximported_module_var_set.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: k, show\n"
        "integer, save :: k\n"
        "contains\n"
        "subroutine show()\n"
        "print *, k\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m, only: k, show\n"
        "implicit none\n"
        "k = 7\n"
        "call show()\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["7"]


def test_batch_runner_times_out_file(tmp_path):
    source = tmp_path / "a.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    source.write_text("print *, 11\nend\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        f"\"{sys.executable}\" -c \"import time; time.sleep(2)\"\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--ofort",
            str(fake_ofort),
            "--timeout",
            "0.1",
            str(source),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "==> " in result.stdout
    assert "(2 lines)" in result.stdout
    assert "timed out after 0.1 seconds" in result.stderr
    assert re.search(r"1 of 1 failed in \d+\.\d{2}s", result.stderr)


def test_batch_runner_timeout_ok_continues_past_timeout(tmp_path):
    slow = tmp_path / "a.f90"
    good = tmp_path / "b.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    slow.write_text("print *, 11\nend\n", encoding="utf-8")
    good.write_text("print *, 22\nend\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        "if /I \"%~nx1\"==\"a.f90\" (\n"
        f"  \"{sys.executable}\" -c \"import time; time.sleep(2)\"\n"
        "  exit /b 0\n"
        ")\n"
        "echo handled %~nx1\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--ofort",
            str(fake_ofort),
            "--timeout",
            "0.1",
            "--timeout-ok",
            "--max-fail",
            "1",
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "a.f90" in result.stdout
    assert "handled b.f90" in result.stdout
    assert "timed out after 0.1 seconds" in result.stderr
    assert "stopped after" not in result.stderr
    assert re.search(r"1 passed, 1 skipped, 1 timed out in \d+\.\d{2}s", result.stdout)


def test_batch_runner_known_unsupported_errors_do_not_trigger_max_fail(tmp_path):
    unsupported = tmp_path / "a_unsupported.f90"
    good = tmp_path / "b_good.f90"
    bad = tmp_path / "c_bad.f90"
    unprocessed = tmp_path / "d_unprocessed.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    for source in [unsupported, good, bad, unprocessed]:
        source.write_text("print *, 11\nend\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        "echo handled %~nx1\n"
        "if /I \"%~nx1\"==\"a_unsupported.f90\" (\n"
        "  echo SELECT TYPE is not supported yet 1>&2\n"
        "  exit /b 1\n"
        ")\n"
        "if /I \"%~nx1\"==\"c_bad.f90\" (\n"
        "  echo real failure 1>&2\n"
        "  exit /b 1\n"
        ")\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--ofort",
            str(fake_ofort),
            "--max-fail",
            "1",
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "handled a_unsupported.f90" in result.stdout
    assert "handled b_good.f90" in result.stdout
    assert "handled c_bad.f90" in result.stdout
    assert "handled d_unprocessed.f90" not in result.stdout
    assert "SELECT TYPE is not supported yet" in result.stderr
    assert "real failure" in result.stderr
    assert "stopped after 1 failures; 1 sources not processed" in result.stderr
    assert re.search(r"1 of 4 failed, 1 skipped in \d+\.\d{2}s", result.stderr)


def test_batch_runner_rejects_bad_timeout(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--timeout", "-1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--timeout must be non-negative" in result.stderr


def test_batch_runner_rejects_bad_max_lines(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--max-lines", "-1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--max-lines must be non-negative" in result.stderr


def test_og_manifest_skip_skips_noncomment_entries(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\nend\n", encoding="utf-8")
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text(
        "# comment\n"
        "a.f90\n"
        "\n"
        "b.f90\n"
        "c.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--skip", "2", "--diff"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "outputs match" in result.stdout
    assert "a.f90" not in result.stdout
    assert "b.f90" not in result.stdout


def test_og_manifest_skip_lines_skips_raw_manifest_lines(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\nend\n", encoding="utf-8")
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text(
        "# comment\n"
        "a.f90\n"
        "! another comment\n"
        "b.f90\n"
        "c.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--skip-lines", "3", "--diff"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("outputs match") == 2
    assert "a.f90" not in result.stdout
    assert "b.f90" in result.stdout
    assert "c.f90" in result.stdout


def test_og_manifest_limit_limits_processed_entries(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    (tmp_path / "a.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\nend\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\nend\n", encoding="utf-8")
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text(
        "a.f90\n"
        "# comment\n"
        "b.f90\n"
        "c.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--limit", "2", "--diff"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("outputs match") == 2
    assert "a.f90" in result.stdout
    assert "b.f90" in result.stdout
    assert "c.f90" not in result.stdout


def test_og_manifest_max_fail_stops_after_failures(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    (tmp_path / "good.f90").write_text("print *, 11\nend\n", encoding="utf-8")
    (tmp_path / "bad.f90").write_text(
        "print *, 22\n"
        "call execute_command_line('echo 23')\n"
        "end\n",
        encoding="utf-8",
    )
    (tmp_path / "after.f90").write_text("print *, 33\nend\n", encoding="utf-8")
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text(
        "good.f90\n"
        "bad.f90\n"
        "after.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--diff", "--max-fail", "1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "good.f90" in result.stdout
    assert "bad.f90" in result.stdout
    assert "after.f90" not in result.stdout
    assert "stopped after 1 failures; 1 sources not processed" in result.stderr


def test_og_same_failure_ok_treats_matching_failing_stdout_as_success(tmp_path):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran not available")

    source = tmp_path / "x.f90"
    source.write_text(
        "print *, 'before failure'\n"
        "error stop\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(OG_RUNNER),
            str(source),
            "--same-failure-ok",
            "--diff",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "outputs match\n"


def test_og_same_failure_ok_treats_matching_failure_line_as_success(tmp_path):
    real_gfortran = shutil.which("gfortran")
    if not real_gfortran:
        pytest.skip("gfortran not available")

    source = tmp_path / "x.f90"
    ofort = tmp_path / "fake_ofort.bat"
    source.write_text(
        "character(len=3) :: s\n"
        "print '(a)', 'abc'\n"
        "write(s, '(a)') 'abcd'\n"
        "end\n",
        encoding="utf-8",
    )
    ofort.write_text(
        "@echo off\n"
        f"echo {source}:3: End of record 1>&2\n"
        "echo line 3: write(s, '(a)') 'abcd' 1>&2\n"
        "exit /b 1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(OG_RUNNER),
            str(source),
            "--ofort",
            str(ofort),
            "--same-failure-ok",
            "--diff",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "outputs match\n"


def test_og_no_warn_passes_w_to_gfortran_and_ofort(tmp_path):
    real_gfortran = shutil.which("gfortran")
    if not real_gfortran:
        pytest.skip("gfortran not available")

    source = tmp_path / "x.f90"
    gfortran = tmp_path / "fake_gfortran.bat"
    ofort = tmp_path / "fake_ofort.bat"
    log = tmp_path / "args.log"
    source.write_text("print *, 11\nend\n", encoding="utf-8")
    gfortran.write_text(
        "@echo off\n"
        f"echo gfortran %*>>\"{log}\"\n"
        f"\"{real_gfortran}\" %*\n",
        encoding="utf-8",
    )
    ofort.write_text(
        "@echo off\n"
        f"echo ofort %*>>\"{log}\"\n"
        "echo 11\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(OG_RUNNER),
            str(source),
            "--gfortran",
            str(gfortran),
            "--ofort",
            str(ofort),
            "--no-warn",
            "--diff",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "outputs match\n"
    log_text = log.read_text(encoding="utf-8")
    assert f"gfortran -w {source}" in log_text
    assert f"ofort -w {source}" in log_text


def test_og_rejects_negative_skip(tmp_path):
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--skip", "-1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--skip must be non-negative" in result.stderr


def test_og_rejects_negative_skip_lines(tmp_path):
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--skip-lines", "-1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--skip-lines must be non-negative" in result.stderr


def test_og_rejects_bad_limit(tmp_path):
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--limit", "0"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--limit must be at least 1" in result.stderr


def test_og_rejects_bad_max_fail(tmp_path):
    manifest = tmp_path / "tip_files.txt"
    manifest.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(OG_RUNNER), f"@{manifest}", "--max-fail", "0"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--max-fail must be at least 1" in result.stderr


def test_fixed_form_source_by_extension(tmp_path):
    source = tmp_path / "xfixed.f"
    source.write_text(
        "      program x\n"
        "      integer i\n"
        "      i = 3\n"
        "      print *, i\n"
        "      end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["3"]


def test_fixed_form_forced_on_stdin():
    source = (
        "      program x\n"
        "      print *, 12\n"
        "      end\n"
    )

    result = subprocess.run(
        [str(OFORT), "--fixed-form"],
        cwd=ROOT,
        input=source,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["12"]


def test_save_free_writes_converted_f90(tmp_path):
    source = tmp_path / "xfixed_save.f"
    saved = tmp_path / "xfixed_save.f90"
    source.write_text(
        "      program x\n"
        "      integer i\n"
        "      i = 7\n"
        "      print *, i\n"
        "      end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--save-free", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert saved.exists()
    assert "program x" in saved.read_text(encoding="utf-8").lower()
    assert result.stdout.split()[-1] == "7"


def test_compact_endtype_with_name_checks(tmp_path):
    source = tmp_path / "xcompact_endtype.f90"
    source.write_text(
        "module m\n"
        "  type t\n"
        "    integer :: i\n"
        "  endtype t\n"
        "end module\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_implicit_parameterized_type_and_unlimited_type_check(tmp_path):
    source = tmp_path / "ximplicit_parameterized_type.f90"
    source.write_text(
        "module m\n"
        "  type t(k)\n"
        "    integer, kind :: k = 4\n"
        "    integer(k) :: i\n"
        "  end type\n"
        "end module\n"
        "subroutine s(a, b)\n"
        "  use m\n"
        "  implicit type(t(2))(a), class(t)(c)\n"
        "  type(*) :: b\n"
        "end subroutine\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_semantic_check_allows_module_and_local_type_constructors(tmp_path):
    source = tmp_path / "xtype_constructor_check.f90"
    source.write_text(
        "module m\n"
        "  implicit none\n"
        "  type ty\n"
        "    integer :: i = 1\n"
        "    integer :: j = 2\n"
        "  end type\n"
        "end module\n"
        "program main\n"
        "  use m\n"
        "  implicit none\n"
        "  type con\n"
        "    type(ty) :: x\n"
        "    integer :: k\n"
        "  end type\n"
        "  type(ty) :: a\n"
        "  type(con) :: b\n"
        "  a = ty(3, 4)\n"
        "  b = con(ty(5, 6), 7)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_old_style_character_dimension_then_length_check(tmp_path):
    source = tmp_path / "xold_character_decl.f90"
    source.write_text(
        "subroutine s(a, b, c)\n"
        "  integer :: n\n"
        "  parameter (n = 3)\n"
        "  character a(n)*(*)\n"
        "  character*10 b, c(:)*(*)\n"
        "end subroutine\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_standalone_parameter_updates_existing_local_declaration(tmp_path):
    source = tmp_path / "xparameter_existing_local.f90"
    source.write_text(
        "subroutine s(v)\n"
        "  implicit none\n"
        "  real :: v(50)\n"
        "  integer afctol\n"
        "  parameter (afctol = 31)\n"
        "  v(afctol) = 1.0\n"
        "  print *, v(31)\n"
        "end subroutine\n"
        "program main\n"
        "  implicit none\n"
        "  real :: v(50)\n"
        "  v = 0.0\n"
        "  call s(v)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1.0"]


def test_scalar_kind_promotes_array_expression_for_generic_resolution(tmp_path):
    source = tmp_path / "xkind_promoted_array_generic.f90"
    source.write_text(
        "module m\n"
        "  implicit none\n"
        "  integer, parameter :: dp = kind(1.0d0)\n"
        "  interface set_alloc\n"
        "    module procedure set_alloc_real_vec\n"
        "  end interface\n"
        "contains\n"
        "  subroutine set_alloc_real_vec(x, y)\n"
        "    real(kind=dp), intent(in) :: x(:)\n"
        "    real(kind=dp), allocatable, intent(out) :: y(:)\n"
        "    allocate(y(size(x)))\n"
        "    y = x\n"
        "  end subroutine\n"
        "end module\n"
        "program main\n"
        "  use m\n"
        "  implicit none\n"
        "  real(kind=dp), allocatable :: x(:)\n"
        "  call set_alloc(1.0_dp * [2.1, 0.0, 4.5], x)\n"
        "  print *, size(x), kind(x)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["3", "8"]


def test_derived_type_dimension_assumed_size_check(tmp_path):
    source = tmp_path / "xtype_dimension_star.f90"
    source.write_text(
        "module m\n"
        "  type v\n"
        "    integer :: y\n"
        "  end type\n"
        "contains\n"
        "  subroutine s(z)\n"
        "    type(v), dimension(*) :: z\n"
        "  end subroutine\n"
        "end module\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_character_array_constructor_rejects_mixed_lengths(tmp_path):
    source = tmp_path / "xchar_array.f90"
    source.write_text(
        "implicit none\n"
        "character(len=10) :: s(3)\n"
        "s = [\"one\", \"four\", \"seven\"]\n"
        "print *, s\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Different CHARACTER lengths (3/4) in array constructor" in result.stderr


def test_missing_end_program_is_rejected(tmp_path):
    source = tmp_path / "xno_end.f90"
    source.write_text(
        "program main\n"
        "  implicit none\n"
        "  print *, 1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Unexpected end of file: missing END PROGRAM" in result.stderr


def test_mismatched_end_program_name_is_rejected(tmp_path):
    source = tmp_path / "xbad_end.f90"
    source.write_text(
        "program ab\n"
        "print *, \"hi\"\n"
        "end program a\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Expected label 'ab' for END PROGRAM statement" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("source_text", "expected"),
    [
        (
            "module mod_a\n"
            "contains\n"
            "subroutine s\n"
            "end subroutine s\n"
            "end module mod_b\n",
            "Expected label 'mod_a' for END MODULE statement",
        ),
        (
            "subroutine sub_a\n"
            "print *, \"hi\"\n"
            "end subroutine sub_b\n",
            "Expected label 'sub_a' for END SUBROUTINE statement",
        ),
        (
            "function fun_a()\n"
            "integer :: fun_a\n"
            "fun_a = 1\n"
            "end function fun_b\n",
            "Expected label 'fun_a' for END FUNCTION statement",
        ),
        (
            "type type_a\n"
            "integer :: i\n"
            "end type type_b\n"
            "type(type_a) :: x\n"
            "x%i = 1\n"
            "print *, x%i\n"
            "end\n",
            "Expected label 'type_a' for END TYPE statement",
        ),
        (
            "outer: block\n"
            "print *, 1\n"
            "end block inner\n"
            "end\n",
            "Expected label 'outer' for END BLOCK statement",
        ),
        (
            "integer :: i\n"
            "i = 3\n"
            "outer: associate (j => i)\n"
            "print *, j\n"
            "end associate inner\n"
            "end\n",
            "Expected label 'outer' for END ASSOCIATE statement",
        ),
        (
            "integer :: i\n"
            "i = 1\n"
            "outer: select case (i)\n"
            "case (1)\n"
            "print *, i\n"
            "end select inner\n"
            "end\n",
            "Expected label 'outer' for END SELECT statement",
        ),
        (
            "integer :: i\n"
            "outer: do i = 1, 2\n"
            "print *, i\n"
            "end do inner\n"
            "end\n",
            "Expected label 'outer' for END DO statement",
        ),
        (
            "outer: if (.true.) then\n"
            "print *, 1\n"
            "end if inner\n"
            "end\n",
            "Expected label 'outer' for END IF statement",
        ),
        (
            "logical :: mask(2)\n"
            "integer :: x(2)\n"
            "mask = [.true., .false.]\n"
            "x = 0\n"
            "outer: where (mask)\n"
            "x = 1\n"
            "end where inner\n"
            "print *, x\n"
            "end\n",
            "Expected label 'outer' for END WHERE statement",
        ),
        (
            "integer :: x(2), i\n"
            "x = 0\n"
            "outer: forall (i = 1:2)\n"
            "x(i) = i\n"
            "end forall inner\n"
            "print *, x\n"
            "end\n",
            "Expected label 'outer' for END FORALL statement",
        ),
        (
            "submodule (parent_mod) sub_a\n"
            "end submodule sub_b\n",
            "Expected label 'sub_a' for END SUBMODULE statement",
        ),
        (
            "module procedure proc_a\n"
            "end procedure proc_b\n",
            "Expected label 'proc_a' for END PROCEDURE statement",
        ),
    ],
)
def test_mismatched_named_end_statements_are_rejected(tmp_path, source_text, expected):
    source = tmp_path / "xbad_named_end.f90"
    source.write_text(source_text, encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert expected in result.stderr
    assert result.stdout == ""


def test_file_without_terminal_end_is_rejected(tmp_path):
    source = tmp_path / "xno_end.f90"
    source.write_text(
        "print *, \"hello\"\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Unexpected end of file in" in result.stderr


def test_missing_end_do_is_rejected(tmp_path):
    source = tmp_path / "xno_end_do.f90"
    source.write_text(
        "implicit none\n"
        "integer :: i\n"
        "do i = 1, 3\n"
        "  print *, i\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Unexpected end of file: missing END DO" in result.stderr

def test_import_none_rejects_host_kind_name(tmp_path):
    source = tmp_path / "ximport_none_reject.f90"
    source.write_text(
        """
program ximport_none_reject
implicit none
integer, parameter :: dp = kind(1.0d0)
interface
  subroutine s(x)
    import, none
    real(kind=dp), intent(in) :: x
  end subroutine s
end interface
print *, dp
end program ximport_none_reject
""".lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "IMPORT, NONE prohibits host name 'dp'" in result.stderr
    assert "line 7:     real(kind=dp), intent(in) :: x" in result.stderr

def test_import_none_rejects_host_character_len_name(tmp_path):
    source = tmp_path / "ximport_none_len_reject.f90"
    source.write_text(
        """
program ximport_none_len_reject
implicit none
integer, parameter :: clen = 8
interface
  subroutine s(x)
    import, none
    character(len=clen), intent(in) :: x
  end subroutine s
end interface
print *, clen
end program ximport_none_len_reject
""".lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "IMPORT, NONE prohibits host name 'clen'" in result.stderr
    assert "line 7:     character(len=clen), intent(in) :: x" in result.stderr

def test_import_only_rejects_unimported_host_selector_name(tmp_path):
    source = tmp_path / "ximport_only_reject.f90"
    source.write_text(
        """
program ximport_only_reject
implicit none
integer, parameter :: dp = kind(1.0d0)
integer, parameter :: sp = kind(1.0)
interface
  subroutine s(x, y)
    import, only: dp
    real(kind=dp), intent(in) :: x
    real(kind=sp), intent(in) :: y
  end subroutine s
end interface
print *, dp, sp
end program ximport_only_reject
""".lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "IMPORT, ONLY does not import host name 'sp'" in result.stderr
    assert "line 9:     real(kind=sp), intent(in) :: y" in result.stderr

def test_rejects_procedure_pointer_array(tmp_path):
    source = tmp_path / "xprocedure_pointer_array_reject.f90"
    source.write_text(
        """
program xprocedure_pointer_array_reject
implicit none
abstract interface
  integer function f_int(i)
    integer, intent(in) :: i
  end function f_int
end interface
procedure(f_int), pointer :: p(:)
print *, associated(p)
end program xprocedure_pointer_array_reject
""".lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Procedure pointer arrays are not supported" in result.stderr

def test_rejects_intent_in_procedure_pointer_assignment():
    source = CASES / "xprocedure_pointer_intent_in_assign.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Cannot assign to INTENT(IN) argument 'q'" in result.stderr
    assert "line 22:   q => double_it" in result.stderr

def test_rejects_procedure_pointer_value_conflict():
    source = CASES / "xprocedure_pointer_value_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "VALUE attribute conflicts with POINTER attribute" in result.stderr

def test_rejects_nonpointer_procedure_dummy_pointer_assignment():
    source = CASES / "xprocedure_dummy_nonpointer_assign_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "'f' is not a pointer" in result.stderr
    assert "line 20:   f => double_it" in result.stderr

def test_rejects_procedure_pointer_interface_mismatch():
    source = CASES / "xprocedure_pointer_interface_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "'takes_two' has the wrong number of arguments" in result.stderr
    assert "line 10: p => takes_two" in result.stderr

def test_rejects_procedure_pointer_argument_type_mismatch():
    source = CASES / "xprocedure_pointer_arg_type_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible type" in result.stderr
    assert "line 10: p => takes_real" in result.stderr

def test_rejects_procedure_pointer_argument_kind_mismatch():
    source = CASES / "xprocedure_pointer_arg_kind_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible kind" in result.stderr
    assert "line 10: p => takes_i8" in result.stderr

def test_rejects_procedure_pointer_argument_rank_mismatch():
    source = CASES / "xprocedure_pointer_arg_rank_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible rank" in result.stderr
    assert "line 10: p => takes_array" in result.stderr

def test_rejects_procedure_pointer_argument_intent_mismatch():
    source = CASES / "xprocedure_pointer_arg_intent_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible INTENT" in result.stderr
    assert "line 10: p => takes_inout" in result.stderr

def test_rejects_procedure_pointer_argument_optional_mismatch():
    source = CASES / "xprocedure_pointer_arg_optional_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible OPTIONAL attribute" in result.stderr
    assert "line 10: p => takes_optional" in result.stderr

def test_rejects_procedure_pointer_argument_pointer_mismatch():
    source = CASES / "xprocedure_pointer_arg_pointer_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible POINTER attribute" in result.stderr
    assert "line 12: p => takes_pointer" in result.stderr

def test_rejects_procedure_pointer_argument_allocatable_mismatch():
    source = CASES / "xprocedure_pointer_arg_allocatable_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "argument 'x' has incompatible ALLOCATABLE attribute" in result.stderr
    assert "line 13: p => takes_allocatable" in result.stderr

def test_rejects_procedure_pointer_pure_mismatch():
    source = CASES / "xprocedure_pointer_pure_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "'impure_func' has incompatible PURE attribute" in result.stderr
    assert "line 10: p => impure_func" in result.stderr

def test_rejects_procedure_pointer_elemental_interface():
    source = CASES / "xprocedure_pointer_elemental_interface_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Procedure pointer 'p' shall not have an ELEMENTAL interface" in result.stderr

def test_rejects_procedure_pointer_character_result_length_mismatch():
    source = CASES / "xprocedure_pointer_char_result_len_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "'char5' has incompatible CHARACTER result length" in result.stderr
    assert "line 10: p => char5" in result.stderr

def test_rejects_procedure_pointer_result_kind_mismatch():
    source = CASES / "xprocedure_pointer_result_kind_mismatch_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Interface mismatch in procedure pointer assignment" in result.stderr
    assert "'returns_i4' has incompatible result kind" in result.stderr
    assert "line 10: p => returns_i4" in result.stderr

def test_rejects_parenthesized_procedure_pointer_assignment_target():
    source = CASES / "xprocedure_pointer_paren_lhs_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Invalid pointer assignment target" in result.stderr
    assert "line 10: (p) => add_one" in result.stderr

def test_rejects_parenthesized_assignment_target():
    source = CASES / "xassignment_paren_lhs_reject.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "Invalid assignment target" in result.stderr
    assert "line 4: (i) = 3" in result.stderr

def test_execute_command_line_sets_exit_status_and_runs_shell_command(tmp_path):
    source = tmp_path / "xexecute_command_line.f90"
    out_file = tmp_path / "exec_out.txt"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "integer :: exitstat, cmdstat\n"
        "character(len=80) :: cmdmsg\n"
        f"call execute_command_line(\"echo hello > {out_file}\", exitstat=exitstat, cmdstat=cmdstat, cmdmsg=cmdmsg)\n"
        "print *, exitstat, cmdstat\n"
        "call execute_command_line(\"ofort_command_that_should_not_exist_12345\", exitstat=exitstat, cmdstat=cmdstat)\n"
        "print *, exitstat, cmdstat\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    numbers = [int(s) for s in re.findall(r"-?\d+", result.stdout)]
    assert numbers[:2] == [0, 0]
    assert numbers[2] != 0
    assert numbers[3] == 0
    assert out_file.exists()
    assert "hello" in out_file.read_text(encoding="utf-8")


def test_system_subroutine_runs_shell_command(tmp_path):
    source = tmp_path / "xsystem.f90"
    out_file = tmp_path / "system_out.txt"
    source.write_text(
        "program main\n"
        "call system('echo hello > system_out.txt')\n"
        "print *, 'done'\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "done"
    assert out_file.exists()
    assert "hello" in out_file.read_text(encoding="utf-8")


def test_get_command_reports_command_line_and_arguments(tmp_path):
    source = tmp_path / "xget_command.f90"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "integer :: n, stat\n"
        "character(len=32) :: cmd, arg\n"
        "call get_command(command=cmd, length=n, status=stat)\n"
        "print *, trim(cmd)\n"
        "print *, n, stat, command_argument_count()\n"
        "call get_command_argument(1, arg, length=n, status=stat)\n"
        "print *, trim(arg), n, stat\n"
        "call get_command_argument(2, arg, length=n, status=stat)\n"
        "print *, trim(arg), n, stat\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "alpha", "beta"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "ofort alpha beta" in result.stdout
    assert re.search(r"\b16\s+0\s+2\b", result.stdout)
    assert re.search(r"\balpha\s+5\s+0\b", result.stdout)
    assert re.search(r"\bbeta\s+4\s+0\b", result.stdout)

def test_get_command_zero_length_buffer_sets_positive_status(tmp_path):
    source = tmp_path / "xget_command_zero.f90"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "integer :: n, stat\n"
        "character(len=0) :: cmd\n"
        "call get_command(command=cmd, length=n, status=stat)\n"
        "print *, n, stat\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "--", "alpha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["11", "42"]

def test_get_environment_variable_value_length_status_and_trimming(tmp_path):
    source = tmp_path / "xgetenv.f90"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "character(len=10) :: value\n"
        "character(len=3) :: short\n"
        "integer :: n, stat\n"
        "call get_environment_variable('OFORT_TEST_ENV', value, n, stat)\n"
        "print *, trim(value), n, stat\n"
        "call get_environment_variable('OFORT_TEST_ENV', short, length=n, status=stat)\n"
        "print *, trim(short), n, stat\n"
        "call get_environment_variable('OFORT_TEST_ENV   ', value, status=stat)\n"
        "print *, trim(value), stat\n"
        "call get_environment_variable('OFORT_TEST_ENV   ', status=stat, trim_name=.false.)\n"
        "print *, stat\n"
        "call get_environment_variable('OFORT_TEST_ENV_MISSING', length=n, status=stat)\n"
        "print *, n, stat\n"
        "end program main\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["OFORT_TEST_ENV"] = "abcdef"
    env.pop("OFORT_TEST_ENV_MISSING", None)

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "abcdef", "6", "0",
        "abc", "6", "-1",
        "abcdef", "0",
        "1",
        "0", "1",
    ]

def test_open_status_new_existing_file_sets_iostat_and_errors_without_iostat(tmp_path):
    source = tmp_path / "xopen_new_existing.f90"
    source.write_text(
        "program main\n"
        "implicit none\n"
        "integer :: iu, ierr\n"
        "open(newunit=iu, file='xopen_new_existing.tmp', status='replace', action='write')\n"
        "close(iu)\n"
        "open(newunit=iu, file='xopen_new_existing.tmp', status='new', action='write', iostat=ierr)\n"
        "if (ierr /= 0) print *, 'handled'\n"
        "open(newunit=iu, file='xopen_new_existing.tmp', status='new', action='write')\n"
        "print *, 'not reached'\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "handled" in result.stdout
    assert "Cannot open file 'xopen_new_existing.tmp': File exists" in result.stderr


def test_internal_write_overflow_reports_eor(tmp_path):
    source = tmp_path / "xwrite_char_eor.f90"
    source.write_text(
        "character(len=3) :: s\n"
        "write(s, '(a)') 'abcd'\n"
        "print *, s\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "End of record" in result.stderr


def test_internal_write_to_constructor_initialized_character_component_keeps_length(tmp_path):
    source = tmp_path / "xcomponent_internal_write.f90"
    source.write_text(
        "type type_kind\n"
        "  integer :: k\n"
        "  character(len=8) :: text\n"
        "end type\n"
        "type(type_kind) :: ir(1)\n"
        "ir = type_kind(0, '')\n"
        "ir(1)%k = selected_int_kind(1)\n"
        "write(unit=ir(1)%text, fmt=\"(\"\"  Int_\"\",I2.2)\") ir(1)%k\n"
        "print *, '[' // ir(1)%text // ']'\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[  Int_01]"


def test_fast_empty_main_skips_unreachable_top_level_procedure_checks(tmp_path):
    source = tmp_path / "xfast_empty_main.f90"
    source.write_text(
        "module unused_mod\n"
        "contains\n"
        "pure subroutine invalid_if_checked()\n"
        "  print *, 99\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "implicit none\n"
        "end program main\n",
        encoding="utf-8",
    )

    normal = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert normal.returncode != 0
    assert "PRINT statement is not allowed in PURE procedure" in normal.stderr
    assert fast.returncode == 0, fast.stderr
    assert fast.stdout == ""


def test_fast_reachable_prunes_unused_module_procedure_bodies(tmp_path):
    source = tmp_path / "xreachable.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "contains\n"
        "pure function used(x) result(y)\n"
        "real(kind=dp), intent(in) :: x(:)\n"
        "real(kind=dp) :: y(size(x))\n"
        "y = x + 1.0_dp\n"
        "end function used\n"
        "pure subroutine unused_bad()\n"
        "print *, 99\n"
        "end subroutine unused_bad\n"
        "end module m\n"
        "program main\n"
        "use m, only: used\n"
        "implicit none\n"
        "print *, used(1.0d0 * [10, 20, 30])\n"
        "end program main\n",
        encoding="utf-8",
    )

    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    reachable = subprocess.run(
        [str(OFORT), "--fast", "--reachable", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert fast.returncode != 0
    assert "PRINT statement is not allowed in PURE procedure" in fast.stderr
    assert reachable.returncode == 0, reachable.stderr
    assert reachable.stdout.split() == ["11.0", "21.0", "31.0"]


def test_fast_reachable_can_write_pruned_source(tmp_path):
    source = tmp_path / "xreachable_write.f90"
    pruned = tmp_path / "xreachable_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "integer function used()\n"
        "used = 7\n"
        "end function used\n"
        "subroutine unused()\n"
        "print *, 99\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: used\n"
        "print *, used()\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    text = pruned.read_text(encoding="utf-8")
    assert text.startswith("! Generated by ofort --write-reachable\n! Command: ")
    assert "--write-reachable" in text.splitlines()[1]
    assert str(source) in text.splitlines()[1]
    assert "integer function used()" in text
    assert "subroutine unused()" not in text
    assert "module procedure unused" not in text
    assert "program main" in text
    run = subprocess.run(
        [str(OFORT), "--fast", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["7"]


def test_write_reachable_does_not_require_fast(tmp_path):
    source = tmp_path / "xreachable_write_no_fast.f90"
    pruned = tmp_path / "xreachable_write_no_fast_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "integer function used()\n"
        "used = 8\n"
        "end function used\n"
        "subroutine unused()\n"
        "print *, 99\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: used\n"
        "print *, used()\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    text = pruned.read_text(encoding="utf-8")
    assert "integer function used()" in text
    assert "subroutine unused()" not in text
    run = subprocess.run(
        [str(OFORT), str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["8"]


def test_write_reachable_keeps_complete_procedure_with_internal_helpers(tmp_path):
    source = tmp_path / "xreachable_internal_proc.f90"
    pruned = tmp_path / "xreachable_internal_proc_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "subroutine sort2(x)\n"
        "real, intent(inout) :: x(:)\n"
        "call swap_if_needed(1, 2)\n"
        "contains\n"
        "subroutine swap_if_needed(i, j)\n"
        "integer, intent(in) :: i, j\n"
        "real :: tmp\n"
        "if (x(i) > x(j)) then\n"
        "   tmp = x(i)\n"
        "   x(i) = x(j)\n"
        "   x(j) = tmp\n"
        "end if\n"
        "end subroutine swap_if_needed\n"
        "end subroutine sort2\n"
        "subroutine unused()\n"
        "print *, 99\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: sort2\n"
        "real :: x(2)\n"
        "x = [2.0, 1.0]\n"
        "call sort2(x)\n"
        "print *, x\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "subroutine sort2" in text
    assert "subroutine swap_if_needed" in text
    assert "end subroutine sort2" in text
    assert "subroutine unused" not in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run(
        [str(OFORT), str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["1.0", "2.0"]


def test_write_reachable_ignores_function_word_in_string_literals(tmp_path):
    source = tmp_path / "xreachable_function_string.f90"
    pruned = tmp_path / "xreachable_function_string_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "integer function f()\n"
        "print *, \"no matching function for name\"\n"
        "f = 1\n"
        "end function f\n"
        "integer function g()\n"
        "g = f() + 1\n"
        "end function g\n"
        "subroutine unused()\n"
        "print *, 99\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: g\n"
        "integer :: i\n"
        "i = g()\n"
        "print *, i\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "end function f" in text
    assert text.index("end function f") < text.index("integer function g")
    assert "subroutine unused" not in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run(
        [str(OFORT), str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["no", "matching", "function", "for", "name", "2"]


def test_write_reachable_keeps_generic_interface_dependencies(tmp_path):
    source = tmp_path / "xreachable_generic.f90"
    pruned = tmp_path / "xreachable_generic_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: both\n"
        "interface default\n"
        "   module procedure default_logical\n"
        "end interface default\n"
        "contains\n"
        "elemental function default_logical(def, opt) result(tf)\n"
        "logical, intent(in) :: def\n"
        "logical, intent(in), optional :: opt\n"
        "logical :: tf\n"
        "if (present(opt)) then\n"
        "   tf = opt\n"
        "else\n"
        "   tf = def\n"
        "end if\n"
        "end function default_logical\n"
        "elemental function both(xx, yy) result(tf)\n"
        "logical, intent(in), optional :: xx, yy\n"
        "logical :: tf\n"
        "tf = default(.true., xx) .and. default(.true., yy)\n"
        "end function both\n"
        "subroutine unused()\n"
        "print *, 99\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: both\n"
        "print *, both(.true., .false.)\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "interface default" in text
    assert "module procedure default_logical" in text
    assert "elemental function default_logical" in text
    assert "elemental function both" in text
    assert "subroutine unused" not in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run(
        [str(OFORT), str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["F"]


def test_write_reachable_removes_unreachable_duplicate_generic_module(tmp_path):
    source = tmp_path / "xreachable_duplicate_generic.f90"
    pruned = tmp_path / "xreachable_duplicate_generic_pruned.f90"
    source.write_text(
        "module used_mod\n"
        "implicit none\n"
        "interface default\n"
        "   module procedure default_integer\n"
        "end interface default\n"
        "contains\n"
        "integer function default_integer(def, opt)\n"
        "integer, intent(in) :: def\n"
        "integer, intent(in), optional :: opt\n"
        "default_integer = def\n"
        "if (present(opt)) default_integer = opt\n"
        "end function default_integer\n"
        "integer function value()\n"
        "value = default(11)\n"
        "end function value\n"
        "end module used_mod\n"
        "\n"
        "module unused_mod\n"
        "implicit none\n"
        "interface default\n"
        "   module procedure default_integer\n"
        "end interface default\n"
        "contains\n"
        "integer function default_integer(def, opt)\n"
        "integer, intent(in) :: def\n"
        "integer, intent(in), optional :: opt\n"
        "default_integer = -1\n"
        "end function default_integer\n"
        "end module unused_mod\n"
        "\n"
        "program main\n"
        "use used_mod, only: value\n"
        "print *, value()\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "module used_mod" in text
    assert "module unused_mod" not in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr


def test_write_reachable_keeps_exports_named_only_in_main_use(tmp_path):
    source = tmp_path / "xreachable_unused_use_only_export.f90"
    pruned = tmp_path / "xreachable_unused_use_only_export_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: g, label\n"
        "interface g\n"
        "module procedure g_int\n"
        "end interface\n"
        "character(len=*), parameter :: label = 'x'\n"
        "contains\n"
        "integer function g_int(i)\n"
        "integer, intent(in) :: i\n"
        "g_int = i + 1\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m, only: g, label\n"
        "print *, 3\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "interface g" in text
    assert "module procedure g_int" in text
    assert "label = 'x'" in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr


def test_write_reachable_filters_private_access_lists(tmp_path):
    source = tmp_path / "xreachable_private_access.f90"
    pruned = tmp_path / "xreachable_private_access_pruned.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private :: unused\n"
        "contains\n"
        "integer function used()\n"
        "used = 4\n"
        "end function\n"
        "integer function unused()\n"
        "unused = 9\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m, only: used\n"
        "print *, used()\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    text = pruned.read_text(encoding="utf-8")
    assert "private :: unused" not in text
    compile_result = subprocess.run(
        ["gfortran", "-Wfatal-errors", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert compile_result.returncode == 0, compile_result.stderr


def test_fast_reachable_write_keeps_same_named_local_module_helper(tmp_path):
    source = tmp_path / "xreachable_same_name.f90"
    pruned = tmp_path / "xreachable_same_name_pruned.f90"
    source.write_text(
        "module strings_mod\n"
        "implicit none\n"
        "contains\n"
        "integer function helper(i)\n"
        "integer, intent(in) :: i\n"
        "helper = i + 100\n"
        "end function helper\n"
        "end module strings_mod\n"
        "module m\n"
        "implicit none\n"
        "contains\n"
        "integer function used(i)\n"
        "integer, intent(in) :: i\n"
        "used = helper(i)\n"
        "end function used\n"
        "integer function helper(i)\n"
        "integer, intent(in) :: i\n"
        "helper = i + 1\n"
        "end function helper\n"
        "end module m\n"
        "program main\n"
        "use strings_mod, only: helper\n"
        "use m, only: used\n"
        "print *, used(2), helper(2)\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    text = pruned.read_text(encoding="utf-8")
    assert text.startswith("! Generated by ofort --write-reachable\n! Command: ")
    assert "--write-reachable" in text.splitlines()[1]
    assert str(source) in text.splitlines()[1]
    assert text.count("integer function helper(i)") == 2
    run = subprocess.run(
        [str(OFORT), "--fast", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["3", "102"]


def test_fast_reachable_write_removes_unused_private_module_variables(tmp_path):
    source = tmp_path / "xreachable_private_vars.f90"
    pruned = tmp_path / "xreachable_private_vars_pruned.f90"
    source.write_text(
        "module kind_mod\n"
        "implicit none\n"
        "private\n"
        "public :: dp, long_int, i64\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "integer, parameter :: long_int = selected_int_kind(15), i64 = long_int\n"
        "end module kind_mod\n"
        "module m\n"
        "use kind_mod, only: dp, long_int, i64\n"
        "implicit none\n"
        "private\n"
        "public :: used\n"
        "integer :: unused_scalar\n"
        "integer, allocatable :: unused_array(:,:)\n"
        "character(len=*), parameter :: label = 'used', unused_label = 'unused'\n"
        "type :: unused_type\n"
        "integer :: value\n"
        "end type unused_type\n"
        "contains\n"
        "function used(x) result(y)\n"
        "real(kind=dp), intent(in) :: x(:)\n"
        "real(kind=dp) :: y(size(x))\n"
        "y = x + 1.0_dp\n"
        "end function used\n"
        "subroutine unused()\n"
        "unused_scalar = 1\n"
        "end subroutine unused\n"
        "end module m\n"
        "program main\n"
        "use m, only: used\n"
        "print *, used(1.0d0 * [10, 20, 30])\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", "--reachable", "--write-reachable", str(pruned), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    text = pruned.read_text(encoding="utf-8")
    assert text.startswith("! Generated by ofort --write-reachable\n! Command: ")
    assert "--write-reachable" in text.splitlines()[1]
    assert str(source) in text.splitlines()[1]
    assert "unused_scalar" not in text
    assert "unused_array" not in text
    assert "unused_label" not in text
    assert "unused_type" not in text
    assert "use kind_mod, only: dp\n" in text
    assert "use kind_mod, only: dp, long_int" not in text
    assert "public :: dp\n" in text
    assert "long_int" not in text
    assert "i64" not in text
    assert "end module kind_mod\n\nmodule m" in text
    assert "end module m\n\nprogram main" in text
    run = subprocess.run(
        [str(OFORT), "--fast", str(pruned)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["11.0", "21.0", "31.0"]


def test_function_result_name_is_read_as_variable(tmp_path):
    source = tmp_path / "xresult_name_read.f90"
    source.write_text(
        "module m\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "contains\n"
        "real(dp) function logistic(x)\n"
        "real(dp), intent(in) :: x\n"
        "logistic = 1.0_dp / (1.0_dp + exp(-x))\n"
        "logistic = min(max(logistic, 1.0e-5_dp), 1.0_dp - 1.0e-5_dp)\n"
        "end function logistic\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "print *, logistic(0.0_dp)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0.5"]


def test_unused_procs_reports_unreachable_contained_procedure(tmp_path):
    source = tmp_path / "xunused.f90"
    source.write_text(
        "program main\n"
        "  call used()\n"
        "contains\n"
        "  subroutine used()\n"
        "    call helper()\n"
        "  end subroutine\n"
        "  subroutine helper()\n"
        "  end subroutine\n"
        "  subroutine dead()\n"
        "  end subroutine\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--unused-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "ofort-unused-procs-v1",
        "status\tkind\tname\tmodule\tfile\tline\tglobal_line",
    ]
    assert len(lines) == 3
    fields = lines[2].split("\t")
    assert fields[:4] == ["unused", "subroutine", "dead", ""]
    assert fields[4] == str(source)
    assert fields[5:] == ["9", "9"]


def test_unused_procs_dep_output_maps_module_file(tmp_path):
    module = tmp_path / "m.f90"
    main = tmp_path / "xmain.f90"
    module.write_text(
        "module m\n"
        "contains\n"
        "  subroutine used()\n"
        "  end subroutine\n"
        "  subroutine dead_mod()\n"
        "  end subroutine\n"
        "end module\n",
        encoding="utf-8",
    )
    main.write_text(
        "program main\n"
        "  use m\n"
        "  call used()\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--dep", "--unused-procs", str(main)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    fields = result.stdout.splitlines()[2].split("\t")
    assert fields[:4] == ["unused", "subroutine", "dead_mod", "m"]
    assert fields[4] == str(module)
    assert fields[5] == "5"


def test_ofort_prune_dry_run_reports_removal_span(tmp_path):
    source = tmp_path / "xprune.f90"
    source.write_text(
        "program main\n"
        "  call used()\n"
        "contains\n"
        "  subroutine used()\n"
        "    print *, 7\n"
        "  end subroutine\n"
        "  subroutine dead()\n"
        "    print *, 99\n"
        "  end subroutine dead\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(PRUNE_RUNNER), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"would-remove\t{source}\t7\t9\tsubroutine\t\tdead"
    ]
    assert "subroutine dead" in source.read_text(encoding="utf-8")


def test_ofort_prune_write_removes_unused_proc_and_creates_backup(tmp_path):
    source = tmp_path / "xprune_write.f90"
    source.write_text(
        "program main\n"
        "  call used()\n"
        "contains\n"
        "  subroutine used()\n"
        "    print *, 7\n"
        "  end subroutine\n"
        "  subroutine dead()\n"
        "    print *, 99\n"
        "  end subroutine dead\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(PRUNE_RUNNER), "--write", "--backup", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"remove\t{source}\t7\t9\tsubroutine\t\tdead"
    ]
    text = source.read_text(encoding="utf-8")
    assert "subroutine dead" not in text
    assert source.with_suffix(".f90.bak").exists()

    run = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert run.returncode == 0, run.stderr
    assert run.stdout.split() == ["7"]


def test_long_public_access_list_is_accepted(tmp_path):
    names = [f"p{i}" for i in range(270)]
    declarations = "\n".join(f"integer, parameter :: p{i} = {i}" for i in range(270))
    source = tmp_path / "xlong_public.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        f"public :: {','.join(names)}\n"
        f"{declarations}\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "print *, p0, p269\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "269"]


def test_getcwd_extension_returns_current_directory(tmp_path):
    source = tmp_path / "xgetcwd.f90"
    source.write_text(
        "character(len=512) :: cwd\n"
        "call getcwd(cwd)\n"
        "print *, len_trim(cwd) > 0\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T"]


def test_named_optional_subroutine_arguments_skip_absent_dummy(tmp_path):
    source = tmp_path / "xnamed_subroutine_args.f90"
    source.write_text(
        "subroutine s(a, b, c, d)\n"
        "integer, intent(in) :: a\n"
        "integer, intent(out), optional :: b, c, d\n"
        "if (present(b)) b = 10\n"
        "if (present(c)) c = 20\n"
        "if (present(d)) d = 30\n"
        "end\n"
        "integer :: x, y\n"
        "call s(1, c=x, d=y)\n"
        "print *, x, y\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["20", "30"]


def test_allocatable_character_dummy_keeps_actual_length(tmp_path):
    source = tmp_path / "xchar_alloc_dummy_len.f90"
    source.write_text(
        "module m\n"
        "contains\n"
        "subroutine set_chars(x, y)\n"
        "character(len=*), intent(in) :: x(:)\n"
        "character(len=*), intent(out), allocatable :: y(:)\n"
        "print *, 'dummy len', len(y)\n"
        "allocate(y(size(x)))\n"
        "y = x\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "character(len=10) :: words(3) = [character(len=10) :: 'dog','cat','four']\n"
        "character(len=10), allocatable :: out(:)\n"
        "call set_chars(words, out)\n"
        "print *, len(out), trim(out(1)), trim(out(2)), trim(out(3))\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["dummy", "len", "10", "10", "dog", "cat", "four"]


def test_concat_manifest_writes_files_with_blank_line_between(tmp_path):
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "a.f90").write_text("print *, 1\n", encoding="utf-8")
    (subdir / "b.f90").write_text("print *, 2", encoding="utf-8")
    manifest = subdir / "files.txt"
    manifest.write_text("a.f90\n\n# comment\nb.f90\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(CONCAT_MANIFEST), str(manifest)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "print *, 1\n\nprint *, 2"


def test_compile_manifest_defaults_to_gfortran_style_command(tmp_path):
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "m.f90").write_text("module m\nend module\n", encoding="utf-8")
    (subdir / "main.f90").write_text("program main\nuse m\nend program\n", encoding="utf-8")
    manifest = tmp_path / "files.txt"
    manifest.write_text("src/m.f90\nsrc/main.f90\n", encoding="utf-8")
    log = tmp_path / "compile.log"
    fake_compiler = tmp_path / "fake_compiler.py"
    fake_compiler.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(log)!r}).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(COMPILE_MANIFEST),
            str(manifest),
            "--compiler",
            f'"{sys.executable}" "{fake_compiler}"',
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    log_text = log.read_text(encoding="utf-8")
    assert str((subdir / "m.f90").resolve()) in log_text
    assert str((subdir / "main.f90").resolve()) in log_text
    assert " -o " in f" {log_text} "
    default_exe = "a.exe" if sys.platform.startswith("win") else "a.out"
    assert str((tmp_path / default_exe).resolve()) in log_text


def test_compile_manifest_ifx_uses_windows_exe_option(tmp_path):
    source = tmp_path / "main.f90"
    source.write_text("end\n", encoding="utf-8")
    manifest = tmp_path / "files.txt"
    manifest.write_text("main.f90\n", encoding="utf-8")
    log = tmp_path / "compile.log"
    fake_compiler = tmp_path / "fake_compiler.py"
    fake_compiler.write_text(
        "import pathlib\n"
        "import sys\n"
        f"pathlib.Path({str(log)!r}).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(COMPILE_MANIFEST),
            str(manifest),
            "--ifx",
            "--compiler",
            f'"{sys.executable}" "{fake_compiler}"',
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    log_text = log.read_text(encoding="utf-8")
    if sys.platform.startswith("win"):
        assert any(arg.startswith("/exe:") for arg in log_text.split())
        assert str((tmp_path / "a.exe").resolve()) in log_text
    else:
        assert " -o " in f" {log_text} "
        assert str((tmp_path / "a.out").resolve()) in log_text


def test_xofort_make_target_filters_program(tmp_path):
    makefile = tmp_path / "Makefile"
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")
    makefile.write_text(
        "FC = gfortran\n"
        "all: a.exe b.exe\n"
        "a.exe: a.f90\n"
        "\t$(FC) a.f90 -o a.exe\n"
        "b.exe: b.f90\n"
        "\t$(FC) b.f90 -o b.exe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--target",
            "b",
            "--list",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "programs: 1" in result.stdout
    assert "b.exe" in result.stdout
    assert "b.f90" in result.stdout
    assert "a.f90" not in result.stdout


def test_xofort_make_target_with_suffix_does_not_match_object_target(tmp_path):
    makefile = tmp_path / "Makefile"
    (tmp_path / "xnagarch.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "kind.f90").write_text("print *, 22\n", encoding="utf-8")
    makefile.write_text(
        "FC = gfortran\n"
        "xnagarch.exe: kind.f90 xnagarch.f90\n"
        "\t$(FC) kind.f90 xnagarch.f90 -o xnagarch.exe\n"
        "xnagarch.o: xnagarch.f90 kind.f90\n"
        "\t$(FC) -c xnagarch.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--target",
            "xnagarch.exe",
            "--list",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "programs: 1" in result.stdout
    assert "[1/1] xnagarch.exe" in result.stdout
    assert "xnagarch.o" not in result.stdout


def test_xofort_make_follows_object_dependencies(tmp_path):
    makefile = tmp_path / "Makefile"
    (tmp_path / "m.f90").write_text("module m\nend module m\n", encoding="utf-8")
    (tmp_path / "main.f90").write_text(
        "program main\nuse m\nprint *, 11\nend program main\n",
        encoding="utf-8",
    )
    makefile.write_text(
        "FC = gfortran\n"
        "main.exe: main.o\n"
        "\t$(FC) -o main.exe main.o m.o\n"
        "main.o: main.f90 m.o\n"
        "\t$(FC) -c main.f90\n"
        "m.o: m.f90\n"
        "\t$(FC) -c m.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--target",
            "main.exe",
            "--list",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "sources: m.f90 main.f90" in result.stdout


def test_xofort_make_forwards_fast_to_ofort(tmp_path):
    makefile = tmp_path / "Makefile"
    log = tmp_path / "args.txt"
    (tmp_path / "main.f90").write_text("print *, 11\n", encoding="utf-8")
    if sys.platform.startswith("win"):
        fake_ofort = tmp_path / "fake_ofort.bat"
        fake_ofort.write_text(
            "@echo off\n"
            f"(for %%A in (%*) do echo %%~A) > \"{log}\"\n"
            "exit /b 0\n",
            encoding="utf-8",
        )
    else:
        fake_ofort = tmp_path / "fake_ofort.py"
        fake_ofort.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib\n"
            "import sys\n"
            f"pathlib.Path({str(log)!r}).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n",
            encoding="utf-8",
        )
        fake_ofort.chmod(0o755)
    makefile.write_text(
        "FC = gfortran\n"
        "main.exe: main.f90\n"
        "\t$(FC) main.f90 -o main.exe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--ofort",
            str(fake_ofort),
            "--target",
            "main.exe",
            "--fast",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = log.read_text(encoding="utf-8").splitlines()
    assert args[0] == "--fast"
    assert str((tmp_path / "main.f90").resolve()) in args


def test_xofort_make_live_output_times_out(tmp_path):
    makefile = tmp_path / "Makefile"
    if sys.platform.startswith("win"):
        fake_ofort = tmp_path / "fake_ofort.bat"
        fake_ofort.write_text(
            "@echo off\n"
            "echo before sleep\n"
            f"\"{sys.executable}\" -c \"import time; time.sleep(2)\"\n",
            encoding="utf-8",
        )
    else:
        fake_ofort = tmp_path / "fake_ofort.py"
        fake_ofort.write_text(
            "#!/usr/bin/env python3\n"
            "import time\n"
            "print('before sleep', flush=True)\n"
            "time.sleep(2)\n",
            encoding="utf-8",
        )
        fake_ofort.chmod(0o755)
    (tmp_path / "main.f90").write_text("print *, 11\n", encoding="utf-8")
    makefile.write_text(
        "FC = gfortran\n"
        "main.exe: main.f90\n"
        "\t$(FC) main.f90 -o main.exe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--ofort",
            str(fake_ofort),
            "--target",
            "main.exe",
            "--timeout",
            "0.1",
            "--live-output",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "before sleep" in result.stdout
    assert "TIMEOUT" in result.stdout


def test_xofort_make_write_source_writes_concatenated_program(tmp_path):
    makefile = tmp_path / "Makefile"
    output = tmp_path / "combined.f90"
    (tmp_path / "m.f90").write_text("module m\nend module m\n", encoding="utf-8")
    (tmp_path / "main.f90").write_text(
        "program main\nuse m\nprint *, 11\nend program main\n",
        encoding="utf-8",
    )
    makefile.write_text(
        "FC = gfortran\n"
        "main.exe: main.o\n"
        "\t$(FC) -o main.exe main.o m.o\n"
        "main.o: main.f90 m.o\n"
        "\t$(FC) -c main.f90\n"
        "m.o: m.f90\n"
        "\t$(FC) -c m.f90\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--target",
            "main.exe",
            "--write-source",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "wrote source:" in result.stdout
    text = output.read_text(encoding="utf-8")
    assert "Generated by xofort_make.py --write-source" in text
    assert "! >>> m.f90" in text
    assert "! >>> main.f90" in text
    assert text.index("module m") < text.index("program main")


def test_xofort_make_write_source_requires_one_program(tmp_path):
    makefile = tmp_path / "Makefile"
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")
    makefile.write_text(
        "FC = gfortran\n"
        "a.exe: a.f90\n"
        "\t$(FC) a.f90 -o a.exe\n"
        "b.exe: b.f90\n"
        "\t$(FC) b.f90 -o b.exe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--write-source",
            str(tmp_path / "combined.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "--write-source requires exactly one inferred program" in result.stderr


def test_xofort_make_target_reports_missing_target(tmp_path):
    makefile = tmp_path / "Makefile"
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    makefile.write_text(
        "FC = gfortran\n"
        "a: a.f90\n"
        "\t$(FC) a.f90 -o a.exe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(XOFORT_MAKE),
            str(makefile),
            "--target",
            "missing",
            "--list",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "target not found or has no Fortran source dependencies: missing" in result.stderr


def test_module_variable_update_survives_nested_module_function_call(tmp_path):
    source = tmp_path / "xmodule_var_nested_function.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: s\n"
        "integer, parameter :: istdout = 6\n"
        "integer :: old_time_\n"
        "contains\n"
        "integer function default(i, j)\n"
        "integer, intent(in) :: i\n"
        "integer, intent(in), optional :: j\n"
        "if (present(j)) then\n"
        "  default = j\n"
        "else\n"
        "  default = i\n"
        "end if\n"
        "end function\n"
        "subroutine s(old_time, fmt_trailer, outu)\n"
        "integer, intent(in), optional :: old_time\n"
        "character(len=*), intent(in), optional :: fmt_trailer\n"
        "integer, intent(in), optional :: outu\n"
        "integer :: new_time, itick, outu_\n"
        "character(len=100) :: fmt_time_\n"
        "if (present(old_time)) then\n"
        "  old_time_ = old_time\n"
        "else\n"
        "  call system_clock(old_time_)\n"
        "end if\n"
        "outu_ = default(istdout, outu)\n"
        "fmt_time_ = '(l1)'\n"
        "call system_clock(new_time, itick)\n"
        "write(outu_, fmt_time_) old_time_ > 0 .and. new_time >= old_time_\n"
        "if (present(fmt_trailer)) print *, trim(fmt_trailer)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m, only: s\n"
        "implicit none\n"
        "integer :: t1\n"
        "call system_clock(t1)\n"
        "call s(t1, fmt_trailer='done')\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T", "done"]


def test_fast_specializes_pythag_unless_disabled(tmp_path):
    source = tmp_path / "xfast_pythag.f90"
    source.write_text(
        "module pythag_mod\n"
        "implicit none\n"
        "contains\n"
        "pure function pythag(a,b)\n"
        "real(8), intent(in) :: a, b\n"
        "real(8) :: pythag\n"
        "real(8) :: absa, absb\n"
        "absa = abs(a)\n"
        "absb = abs(b)\n"
        "if (absa > absb) then\n"
        "   pythag = absa*sqrt(1.0d0+(absb/absa)**2)\n"
        "else if (absb == 0.0d0) then\n"
        "   pythag = 0.0d0\n"
        "else\n"
        "   pythag = absb*sqrt(1.0d0+(absa/absb)**2)\n"
        "end if\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use pythag_mod\n"
        "print '(f6.2,1x,f6.2)', pythag(3.0d0, 4.0d0), pythag(0.0d0, 0.0d0)\n"
        "end program\n",
        encoding="utf-8",
    )

    fast = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    unspecialized = subprocess.run(
        [str(OFORT), "--fast", "--no-specialize", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert fast.returncode == 0, fast.stderr
    assert unspecialized.returncode == 0, unspecialized.stderr
    assert fast.stdout == unspecialized.stdout == "  5.00   0.00\n"


def test_fast_nested_optional_array_outputs_with_automatic_arrays(tmp_path):
    source = tmp_path / "xfast_optional_array_chain.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "contains\n"
        "function f(a, b) result(y)\n"
        "real(kind=dp), intent(in) :: a(:,:)\n"
        "real(kind=dp), intent(in) :: b(:)\n"
        "real(kind=dp) :: y(size(b))\n"
        "real(kind=dp), allocatable :: x(:)\n"
        "allocate(x(size(a,2)))\n"
        "call s1(a, b, x, y)\n"
        "end function\n"
        "subroutine s1(a, b, x, y)\n"
        "real(kind=dp), intent(in) :: a(:,:)\n"
        "real(kind=dp), intent(in) :: b(:)\n"
        "real(kind=dp), intent(out) :: x(:)\n"
        "real(kind=dp), intent(out), optional :: y(:)\n"
        "real(kind=dp) :: z(size(x))\n"
        "call s2(a, b, x, std=z, pred=y)\n"
        "end subroutine\n"
        "subroutine s2(a, b, x, std, pred)\n"
        "real(kind=dp), intent(in) :: a(:,:)\n"
        "real(kind=dp), intent(in) :: b(:)\n"
        "real(kind=dp), intent(out) :: x(:)\n"
        "real(kind=dp), intent(out), optional :: std(:), pred(:)\n"
        "real(kind=dp) :: z(size(x))\n"
        "real(kind=dp), allocatable :: p(:)\n"
        "x = 1.0_dp\n"
        "z = 2.0_dp\n"
        "allocate(p(size(b)))\n"
        "p = matmul(a, x)\n"
        "if (present(std)) std = z\n"
        "if (present(pred)) pred = p\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "real(kind=dp) :: a(10,3), b(10), y(10)\n"
        "a = 1.0_dp\n"
        "b = 2.0_dp\n"
        "y = f(a, b)\n"
        "print *, y(1), y(10)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["3.0", "3.0"]


def test_fast_specializes_simple_elemental_array_function(tmp_path):
    source = tmp_path / "xelemental_fast_pass.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "contains\n"
        "elemental function squash(x) result(y)\n"
        "real(kind=dp), intent(in) :: x\n"
        "real(kind=dp) :: y\n"
        "y = x / (1.0_dp + abs(x))\n"
        "end function\n"
        "elemental function smooth_bump(x) result(y)\n"
        "real(kind=dp), intent(in) :: x\n"
        "real(kind=dp) :: y\n"
        "y = exp(-x*x) + 0.25_dp*squash(2.0_dp*x - 1.0_dp)\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, parameter :: n = 200\n"
        "real(kind=dp) :: x(n), y(n)\n"
        "integer :: i\n"
        "do i = 1, n\n"
        "   x(i) = real(i, dp) / 50.0_dp\n"
        "end do\n"
        "y = smooth_bump(x)\n"
        "print '(f12.6)', sum(y)\n"
        "end program\n",
        encoding="utf-8",
    )

    fast = subprocess.run(
        [str(OFORT), "--fast", "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast_no_specialize = subprocess.run(
        [str(OFORT), "--fast", "--no-specialize", "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    plain = subprocess.run(
        [str(OFORT), "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert fast.returncode == 0, fast.stderr
    assert fast_no_specialize.returncode == 0, fast_no_specialize.stderr
    assert plain.returncode == 0, plain.stderr
    assert fast.stdout.splitlines()[0] == fast_no_specialize.stdout.splitlines()[0] == plain.stdout.splitlines()[0]
    assert re.search(r"\n\s+1\s+[-0-9.]+\s+smooth_bump", fast.stdout + fast.stderr)
    assert re.search(r"\n\s+1\s+[-0-9.]+\s+smooth_bump", fast_no_specialize.stdout + fast_no_specialize.stderr)
    assert re.search(r"\n\s+200\s+[-0-9.]+\s+smooth_bump", plain.stdout + plain.stderr)


def test_fast_elemental_subroutine_bulk_copyback(tmp_path):
    source = tmp_path / "xelemental_subroutine_fast.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "real(kind=dp), parameter :: inv_sqrt2 = 0.707106781186547524400844362104849_dp\n"
        "contains\n"
        "pure elemental function normal_cdf(x) result(p)\n"
        "real(kind=dp), intent(in) :: x\n"
        "real(kind=dp) :: p\n"
        "p = 0.5_dp * (1.0_dp + erf(x * inv_sqrt2))\n"
        "end function\n"
        "pure elemental subroutine black_scholes_put_call(spot, strike, rate, volatility, time, cvalue, pvalue)\n"
        "real(kind=dp), intent(in) :: spot, strike, rate, volatility, time\n"
        "real(kind=dp), intent(out) :: cvalue, pvalue\n"
        "real(kind=dp) :: sqrt_time, vol_sqrt_time, d1, d2, discount\n"
        "sqrt_time = sqrt(time)\n"
        "vol_sqrt_time = volatility * sqrt_time\n"
        "d1 = (log(spot / strike) + (rate + 0.5_dp * volatility * volatility) * time) / vol_sqrt_time\n"
        "d2 = d1 - vol_sqrt_time\n"
        "discount = strike * exp(-rate * time)\n"
        "cvalue = spot * normal_cdf(d1) - discount * normal_cdf(d2)\n"
        "pvalue = discount * normal_cdf(-d2) - spot * normal_cdf(-d1)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, parameter :: n = 100\n"
        "real(kind=dp) :: spot(n), strike(n), rate(n), volatility(n), time(n), call_price(n), put_price(n)\n"
        "integer :: i\n"
        "do i = 1, n\n"
        "   spot(i) = 80.0_dp + real(i, dp) / 5.0_dp\n"
        "   strike(i) = 100.0_dp\n"
        "   rate(i) = 0.03_dp\n"
        "   volatility(i) = 0.20_dp\n"
        "   time(i) = 0.5_dp + real(i, dp) / 200.0_dp\n"
        "end do\n"
        "call black_scholes_put_call(spot, strike, rate, volatility, time, call_price, put_price)\n"
        "print '(f14.6)', sum(call_price) + sum(put_price)\n"
        "end program\n",
        encoding="utf-8",
    )

    fast = subprocess.run(
        [str(OFORT), "--fast", "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    fast_no_specialize = subprocess.run(
        [str(OFORT), "--fast", "--no-specialize", "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    plain = subprocess.run(
        [str(OFORT), "--profile-procs", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert fast.returncode == 0, fast.stderr
    assert fast_no_specialize.returncode == 0, fast_no_specialize.stderr
    assert plain.returncode == 0, plain.stderr
    assert fast.stdout.splitlines()[0] == fast_no_specialize.stdout.splitlines()[0] == plain.stdout.splitlines()[0]
    assert re.search(r"\n\s+1\s+[-0-9.]+\s+black_scholes_put_call", fast.stdout + fast.stderr)
    assert re.search(r"\n\s+1\s+[-0-9.]+\s+black_scholes_put_call", fast_no_specialize.stdout + fast_no_specialize.stderr)
    assert re.search(r"\n\s+100\s+[-0-9.]+\s+black_scholes_put_call", plain.stdout + plain.stderr)


def test_elemental_subroutine_copyback_not_name_sensitive(tmp_path):
    source = tmp_path / "xelemental_copyback_shadow.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "elemental subroutine update(x, y)\n"
        "real, intent(in) :: x\n"
        "real, intent(out) :: y\n"
        "if (x >= 0.0) then\n"
        "   y = x + 1.0\n"
        "else\n"
        "   y = -x\n"
        "end if\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "real :: x(3), y(3)\n"
        "x = [1.0, -2.0, 3.0]\n"
        "call update(x, y)\n"
        "print *, y\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2.0", "2.0", "4.0"]


def test_pack_preserves_derived_array_type_for_generic_resolution(tmp_path):
    source = tmp_path / "xpack_generic_derived.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type :: t\n"
        "   integer :: i\n"
        "end type\n"
        "interface set_alloc\n"
        "   module procedure set_alloc_t\n"
        "end interface\n"
        "contains\n"
        "subroutine set_alloc_t(x, y)\n"
        "type(t), intent(in) :: x(:)\n"
        "type(t), allocatable, intent(out) :: y(:)\n"
        "allocate(y(size(x)))\n"
        "y = x\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "type(t) :: x(3)\n"
        "type(t), allocatable :: y(:)\n"
        "logical :: mask(3)\n"
        "x = [t(1), t(2), t(3)]\n"
        "mask = [.true., .false., .true.]\n"
        "call set_alloc(pack(x, mask), y)\n"
        "print *, size(y), y(1)%i, y(2)%i\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "1", "3"]


def test_vector_subscripted_derived_component_keeps_type_for_generic_resolution(tmp_path):
    source = tmp_path / "xderived_component_vector_subscript_generic.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type :: date_mdy\n"
        "   integer :: month, day, year\n"
        "end type\n"
        "type :: frame\n"
        "   type(date_mdy), allocatable :: dates(:)\n"
        "end type\n"
        "interface set_alloc\n"
        "   module procedure set_alloc_date_mdy\n"
        "end interface\n"
        "contains\n"
        "subroutine set_alloc_date_mdy(x, y)\n"
        "type(date_mdy), intent(in) :: x(:)\n"
        "type(date_mdy), allocatable, intent(out) :: y(:)\n"
        "allocate(y(size(x)))\n"
        "y = x\n"
        "end subroutine\n"
        "function select_dates(df, idx) result(out)\n"
        "type(frame), intent(in) :: df\n"
        "integer, intent(in) :: idx(:)\n"
        "type(frame) :: out\n"
        "call set_alloc(df%dates(idx), out%dates)\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "type(frame) :: df, out\n"
        "allocate(df%dates(3))\n"
        "df%dates = [date_mdy(1, 1, 2000), date_mdy(1, 2, 2000), date_mdy(1, 3, 2000)]\n"
        "out = select_dates(df, [3, 1])\n"
        "print *, size(out%dates), out%dates%day\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "3", "1"]


def test_elemental_derived_array_result_keeps_type_for_generic_resolution(tmp_path):
    source = tmp_path / "xelemental_derived_generic.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type :: date_mdy\n"
        "   integer :: month, day, year\n"
        "end type\n"
        "interface set_alloc\n"
        "   module procedure set_alloc_date_mdy\n"
        "end interface\n"
        "contains\n"
        "pure subroutine set_alloc_date_mdy(x, y)\n"
        "type(date_mdy), intent(in) :: x(:)\n"
        "type(date_mdy), allocatable, intent(out) :: y(:)\n"
        "allocate(y(size(x)))\n"
        "y = x\n"
        "end subroutine\n"
        "elemental function int_to_mdy(i) result(d)\n"
        "integer, intent(in) :: i\n"
        "type(date_mdy) :: d\n"
        "d = date_mdy(1, i, 2000)\n"
        "end function\n"
        "function convert(i) result(out)\n"
        "integer, intent(in) :: i(:)\n"
        "type(date_mdy), allocatable :: out(:)\n"
        "call set_alloc(int_to_mdy(i), out)\n"
        "end function\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "type(date_mdy), allocatable :: d(:)\n"
        "d = convert([2, 3])\n"
        "print *, size(d), d%day\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "2", "3"]


def test_public_type_can_use_private_module_parameters_in_components(tmp_path):
    source = tmp_path / "xtype_private_param_component.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: outer\n"
        "integer, parameter :: npar = 2\n"
        "type :: inner\n"
        "   integer :: i\n"
        "end type\n"
        "type :: outer\n"
        "   type(inner) :: par(npar)\n"
        "end type\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "type(outer) :: x\n"
        "x = outer()\n"
        "print *, size(x%par)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2"]


def test_pointer_dummy_allocate_copyback_and_reallocate(tmp_path):
    source = tmp_path / "xpointer_dummy_allocate.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "contains\n"
        "subroutine fill(p, n)\n"
        "integer, pointer :: p(:)\n"
        "integer, intent(in) :: n\n"
        "integer :: i\n"
        "allocate(p(n))\n"
        "do i = 1, n\n"
        "   p(i) = i\n"
        "end do\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, pointer :: x(:)\n"
        "call fill(x, 2)\n"
        "print *, size(x), x\n"
        "call fill(x, 3)\n"
        "print *, size(x), x\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2", "1", "2", "3", "1", "2", "3"]


def test_scalar_pointer_can_target_array_element(tmp_path):
    source = tmp_path / "xpointer_target.f90"
    source.write_text(
        "implicit none\n"
        "integer, target :: v(3)\n"
        "integer, pointer :: p\n"
        "v = [10, 20, 30]\n"
        "p => v(2)\n"
        "p = 10*p\n"
        "print *, p\n"
        "print *, v\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["200", "10", "200", "30"]


def test_module_allocatable_not_clobbered_by_same_named_dummy_or_local(tmp_path):
    source = tmp_path / "xmodule_alloc_shadow.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, allocatable :: work(:,:)\n"
        "contains\n"
        "recursive subroutine gen(k, x, work)\n"
        "integer, intent(in) :: k\n"
        "integer, intent(inout) :: x(:)\n"
        "integer, intent(inout) :: work(:,:)\n"
        "if (k < 2) call gen(k + 1, x, work)\n"
        "work(1,:) = x\n"
        "end subroutine\n"
        "subroutine build(n)\n"
        "integer, intent(in) :: n\n"
        "integer, allocatable :: x(:)\n"
        "if (allocated(work)) deallocate(work)\n"
        "allocate(x(n), work(2,n))\n"
        "x = [(i, i=1,n)]\n"
        "work(1,:) = x\n"
        "print *, allocated(work), size(work,1), size(work,2), work(1,n)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m, only: gen, build\n"
        "implicit none\n"
        "integer :: i\n"
        "integer, allocatable :: x(:), work(:,:)\n"
        "allocate(x(2), work(2,2))\n"
        "x = 7\n"
        "call gen(1, x, work)\n"
        "call build(3)\n"
        "call build(4)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T", "2", "3", "3", "T", "2", "4", "4"]


def test_zero_size_array_read_does_not_require_initialization(tmp_path):
    source = tmp_path / "xzero_size.f90"
    source.write_text(
        "implicit none\n"
        "integer :: v(0)\n"
        "print *, v\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n"


def test_minval_maxval_zero_size_array_identities(tmp_path):
    source = tmp_path / "xzero_minmax.f90"
    source.write_text(
        "implicit none\n"
        "integer :: i(0)\n"
        "real :: x(0)\n"
        "double precision :: y(0)\n"
        "integer :: a(2,0)\n"
        "print *, minval(i) == huge(i), maxval(i) == -huge(i) - 1\n"
        "print *, minval(x) == huge(x), maxval(x) == -huge(x)\n"
        "print *, minval(y) == huge(y), maxval(y) == -huge(y)\n"
        "print *, size(minval(a, dim=1)), size(maxval(a, dim=1))\n"
        "print *, minval([1,2], mask=[.false., .false.]), maxval([1,2], mask=[.false., .false.])\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "T", "T",
        "T", "T",
        "T", "T",
        "0", "0",
        "2147483647", "-2147483648",
    ]


def test_explicit_shape_dummy_sequence_copyback_preserves_actual_shape(tmp_path):
    source = tmp_path / "xnd.f90"
    source.write_text(
        "program demo\n"
        "implicit none\n"
        "integer, parameter :: n = 2\n"
        "integer :: x(n, n, 2, 1)\n"
        "x = -1\n"
        "call fill_as_2d(x)\n"
        "print \"(100(1x,i0))\", size(x), sum(x), x\n"
        "contains\n"
        "subroutine fill_as_2d(a)\n"
        "integer, intent(out) :: a(n,n)\n"
        "a = 1\n"
        "end subroutine fill_as_2d\n"
        "end program demo\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["8", "0", "1", "1", "1", "1", "-1", "-1", "-1", "-1"]


def test_partial_sequence_copyback_preserves_uninitialized_tail(tmp_path):
    source = tmp_path / "xnd_uninit.f90"
    source.write_text(
        "program demo\n"
        "implicit none\n"
        "integer, parameter :: n = 2\n"
        "integer :: x(n, n, 2, 1)\n"
        "call fill_as_2d(x)\n"
        "print \"(100(1x,i0))\", size(x), sum(x), x\n"
        "contains\n"
        "subroutine fill_as_2d(a)\n"
        "integer, intent(out) :: a(n,n)\n"
        "a = 1\n"
        "end subroutine fill_as_2d\n"
        "end program demo\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Variable 'x' is used before it is fully set" in result.stderr
    assert "first unset element is x(1,1,2,1)" in result.stderr
    assert "sum(x)" in result.stderr


def test_allocatable_component_of_intent_out_derived_dummy_is_definable(tmp_path):
    source = tmp_path / "xalloc_component_intent_out.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type box\n"
        "   integer, allocatable :: a(:)\n"
        "end type\n"
        "contains\n"
        "subroutine set_alloc(x, y)\n"
        "integer, intent(in) :: x(:)\n"
        "integer, allocatable, intent(out) :: y(:)\n"
        "allocate(y(size(x)))\n"
        "y = x\n"
        "end subroutine\n"
        "subroutine fill(src, dst)\n"
        "type(box), intent(in) :: src\n"
        "type(box), intent(out) :: dst\n"
        "if (allocated(src%a)) call set_alloc(src%a, dst%a)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "type(box) :: x, y\n"
        "allocate(x%a(3))\n"
        "x%a = [1, 2, 3]\n"
        "call fill(x, y)\n"
        "print *, allocated(y%a), y%a\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T", "1", "2", "3"]


def test_allocatable_assignment_preserves_declared_kind_for_generic_resolution(tmp_path):
    source = tmp_path / "xgeneric_alloc_kind.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "integer, parameter :: dp = kind(1.0d0)\n"
        "interface show\n"
        "   module procedure show_vec, show_mat\n"
        "end interface\n"
        "contains\n"
        "subroutine show_vec(x, nlags, horizontal)\n"
        "real(kind=dp), intent(in) :: x(:)\n"
        "integer, intent(in) :: nlags\n"
        "logical, intent(in), optional :: horizontal\n"
        "print *, kind(x), size(x), nlags, present(horizontal)\n"
        "end subroutine\n"
        "subroutine show_mat(x, nlags)\n"
        "real(kind=dp), intent(in) :: x(:,:)\n"
        "integer, intent(in) :: nlags\n"
        "print *, size(x), nlags\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "integer, parameter :: n = 4, nacf = 2\n"
        "real(kind=dp), allocatable :: x(:), xsq(:)\n"
        "allocate(x(n))\n"
        "x = 2.0_dp\n"
        "xsq = x**2\n"
        "print *, kind(xsq)\n"
        "call show(xsq, nlags=nacf, horizontal=.true.)\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["8", "8", "4", "2", "T"]


def test_list_directed_internal_read_into_derived_array_element(tmp_path):
    source = tmp_path / "xread_derived_array_element.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "type fund_info\n"
        "   character(len=5) :: ticker\n"
        "   character(len=100) :: name, advisor, category, strategy\n"
        "end type\n"
        "contains\n"
        "subroutine read_one\n"
        "character(len=1000) :: text\n"
        "type(fund_info) :: yinfo(3)\n"
        "type(fund_info), allocatable :: xinfo(:)\n"
        "text = 'ABC name adv cat strat'\n"
        "yinfo%category = '??'\n"
        "read(text, *) yinfo(1)\n"
        "allocate(xinfo(1))\n"
        "xinfo = yinfo(1:1)\n"
        "print *, trim(xinfo(1)%ticker), trim(xinfo(1)%name), trim(xinfo(1)%category)\n"
        "end subroutine\n"
        "end module\n"
        "program main\n"
        "use m\n"
        "call read_one\n"
        "end program\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", "--no-warn-unused", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["ABC", "name", "cat"]
