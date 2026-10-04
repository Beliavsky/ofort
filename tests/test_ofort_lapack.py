"""Optional native LAPACK tests; build with make lapack before running."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"
DEFAULT_LIBRARY = ROOT / ("ofort_lapack_backend.dll" if sys.platform == "win32" else
                          "libofort_lapack_backend.dylib" if sys.platform == "darwin" else
                          "libofort_lapack_backend.so")


def run_source(tmp_path, source, *options):
    path = tmp_path / "test.f90"
    path.write_text(source, encoding="ascii")
    return subprocess.run([str(OFORT), *options, str(path)], cwd=ROOT,
                          capture_output=True, text=True, timeout=15)


@pytest.fixture
def native_backend():
    library = Path(os.environ.get("OFORT_LAPACK_LIBRARY", DEFAULT_LIBRARY))
    if not library.exists():
        pytest.skip("Optional native LAPACK backend is not built")


@pytest.mark.parametrize("fast", [False, True])
def test_native_lapack_solve_query_and_complex(tmp_path, native_backend, fast):
    result = run_source(tmp_path, """program test
use ofort_lapack_mod, only: solve => dgesv, dsyev, zgesv
implicit none
integer :: info, ipiv(2), lwork
double precision :: a(2,2), b(2), w(2)
double precision, allocatable :: work(:)
complex(kind=kind(1.0d0)) :: z(2,2), zb(2)
a = reshape([2d0,1d0,1d0,3d0],[2,2])
b = [4d0,7d0]
call solve(info=info, ldb=2, b=b, ipiv=ipiv, lda=2, a=a, nrhs=1, n=2)
print *, info == 0 .and. maxval(abs(b-[1d0,2d0])) < 1d-12
a = reshape([2d0,1d0,1d0,3d0],[2,2])
allocate(work(1))
call dsyev('V','U',2,a,2,w,work,-1,info)
print *, info == 0 .and. work(1) >= 5d0
lwork = int(work(1))
deallocate(work)
allocate(work(lwork))
call dsyev('V','U',2,a,2,w,work,lwork,info)
print *, info == 0 .and. abs(sum(w)-5d0) < 1d-12
z = cmplx(0d0,0d0,kind(1d0))
z(1,1) = cmplx(2d0,1d0,kind(1d0))
z(2,2) = cmplx(3d0,-1d0,kind(1d0))
zb = [z(1,1),2d0*z(2,2)]
call zgesv(2,1,z,2,ipiv,zb,2,info)
print *, info == 0 .and. maxval(abs(zb-[cmplx(1d0,0d0,kind(1d0)), &
 cmplx(2d0,0d0,kind(1d0))])) < 1d-12
end program
""", *( ["--fast"] if fast else [] ))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["T"] * 4


def test_native_lapack_rejects_short_storage_before_call(tmp_path):
    result = run_source(tmp_path, """program test
use ofort_lapack_mod, only: dgesv
implicit none
double precision :: a(2,2), b(2)
integer :: piv(3), info
a = 1d0
b = 1d0
call dgesv(3,1,a,3,piv,b,3,info)
end program
""")
    assert result.returncode != 0
    assert "needs at least 9 elements; got 4" in result.stderr


def test_native_lapack_check_does_not_load_backend(tmp_path):
    result = run_source(tmp_path, """program test
use ofort_lapack_mod
implicit none
double precision :: a(2,2), b(2)
integer :: piv(2), info
a = 1d0
b = 1d0
call dgesv(2,1,a,2,piv,b,2,info)
end program
""", "--check")
    assert result.returncode == 0, result.stderr


def test_native_lapack_missing_backend_has_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OFORT_LAPACK_LIBRARY", str(tmp_path / "missing_backend.dll"))
    result = run_source(tmp_path, """program test
use ofort_lapack_mod, only: dgesv
implicit none
double precision :: a(1,1), b(1)
integer :: piv(1), info
a = 2d0
b = 4d0
call dgesv(1,1,a,1,piv,b,1,info)
end program
""")
    assert result.returncode != 0
    assert "Cannot load compatible native LAPACK backend" in result.stderr
    assert "OFORT_LAPACK_LIBRARY" in result.stderr


def test_native_lapack_invalid_option_returns_info(tmp_path):
    result = run_source(tmp_path, """program test
use ofort_lapack_mod, only: dpotrf
implicit none
double precision :: a(1,1)
integer :: info
call dpotrf('?',1,a,1,info)
print *, info
end program
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "-1"
