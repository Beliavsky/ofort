module m
implicit none
integer, parameter :: dp = kind(1.0d0)
end module m

program main
use m
implicit none
integer, parameter :: n = 10**3
real(kind=dp) :: x(n)
call random_number(x)
print*,sum(x)/n
print*,sum(x**2)/n
end program main