module twice_mod
implicit none

integer, parameter :: dp = kind(1.0d0)

interface twice
   module procedure twice_int_scalar
   module procedure twice_int_1d
   module procedure twice_real_scalar
   module procedure twice_real_1d
end interface twice

contains

integer function twice_int_scalar(x) result(y)
integer, intent(in) :: x
y = 2 * x
end function twice_int_scalar

function twice_int_1d(x) result(y)
integer, intent(in) :: x(:)
integer :: y(size(x))
y = 2 * x
end function twice_int_1d

real(kind=dp) function twice_real_scalar(x) result(y)
real(kind=dp), intent(in) :: x
y = 2.0_dp * x
end function twice_real_scalar

function twice_real_1d(x) result(y)
real(kind=dp), intent(in) :: x(:)
real(kind=dp) :: y(size(x))
y = 2.0_dp * x
end function twice_real_1d

end module twice_mod

program test_twice
use twice_mod, only: dp, twice
implicit none

integer, parameter :: n = 4
integer :: i
integer :: ia(n)
integer :: ib(n)
real(kind=dp) :: xr
real(kind=dp) :: yr
real(kind=dp) :: ra(n)
real(kind=dp) :: rb(n)

i = 7
xr = 1.25_dp
ia = [1, 2, 3, 4]
ra = [1.0_dp, 2.5_dp, -3.0_dp, 4.25_dp]

ib = twice(ia)
rb = twice(ra)
yr = twice(xr)

print *, "integer scalar:"
print *, "twice(", i, ") =", twice(i)
print *, "real scalar:"
print *, "twice(", xr, ") =", yr
print *, "integer array:"
print *, "ia = ", ia
print *, "twice(ia) = ", ib
print *, "real array:"
print *, "ra = ", ra
print *, "twice(ra) = ", rb

end program test_twice
