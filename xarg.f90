module m
implicit none
contains
function f(x, y) result(z)
real, intent(in) :: x(0:), y(0:)
real :: z
z = sum(x) + sum(y)
end function f
end module m

program main
use m
implicit none
real :: z
z = f([10.0, 20.0], [30.0, 40.0])
print*,z
end program main
