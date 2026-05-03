module m
implicit none
interface set_value
   module procedure set_int, set_real
end interface
contains

subroutine set_int(x)
integer, intent(out) :: x
x = 42
end subroutine set_int

subroutine set_real(x)
real, intent(out) :: x
x = 3.5
end subroutine set_real

end module m

program main
use m
implicit none
integer :: i
real :: x

call set_value(i)
call set_value(x)

print *, i
print *, x
end program main
