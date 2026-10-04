module m
implicit none
integer, parameter :: dp = kind(1.0d0)
interface show
   module procedure show_dp
end interface show
contains
elemental function twice(x) result(y)
real(kind=dp), intent(in) :: x
real(kind=dp)             :: y
y = 2.0_dp*x
end function twice
subroutine show_dp(x, y)
real(kind=dp), intent(in) :: x(:), y(:)
print *, kind(y), int(sum(y))
end subroutine show_dp
end module m

program main
use m
implicit none
real(kind=dp) :: x(2)
x = [1.0_dp, 2.0_dp]
call show(x, twice(x))
end program main
