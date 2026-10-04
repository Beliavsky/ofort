program xtransfer_derived
use iso_fortran_env, only: int64, real64
implicit none

type :: point
   real :: a, b
end type point

real :: x(2)
complex :: z
type(point) :: p
integer(kind=int64) :: i
real(kind=real64) :: d
character(8) :: s

z = (3.0, 4.0)
x = transfer(z, x)
print *, x

p = transfer(x, p)
print *, p

x = transfer(p, x)
print *, x

i = huge(i)
print *, i, transfer(transfer(i, d), i)

s = "aeio+-*/"
print *, s // " " // transfer(transfer(s, d), s)

end program xtransfer_derived
