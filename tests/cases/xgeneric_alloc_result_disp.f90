module m
use, intrinsic :: iso_fortran_env, only: dp => real64
implicit none
interface disp
  module procedure disp_real
  module procedure disp_integer
end interface
contains
subroutine disp_real(x)
real(dp), intent(in) :: x(:)
print "(a,*(1x,f0.1))", "real", x
end subroutine disp_real

subroutine disp_integer(x)
integer, intent(in) :: x(:)
print "(a,*(1x,i0))", "integer", x
end subroutine disp_integer

function half(x) result(y)
real(dp), intent(in) :: x(:)
real(dp), allocatable :: y(:)
y = 0.5_dp*x
end function half
end module m

program main
use m
implicit none
real(dp), allocatable :: x(:)
x = [1, 2, 3]
call disp(half(x))
end program main
