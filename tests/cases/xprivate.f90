module m
implicit none
private
public :: pi
real :: pi=3.14
end module m

program main
use m
implicit none
print*,pi
end program main
