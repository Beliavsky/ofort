program xiso_fortran_env_f2023
use, intrinsic :: iso_fortran_env, only: logical8, logical16, logical32, logical64, real16, l8 => logical8
implicit none
logical(kind=logical8) :: a
logical(kind=logical16) :: b
logical(kind=logical32) :: c
logical(kind=logical64) :: d
a = .true.
b = .false.
c = .true.
d = .false.
print *, logical8, logical16, logical32, logical64, real16, l8
print *, kind(a), kind(b), kind(c), kind(d), a, b, c, d
end program xiso_fortran_env_f2023
