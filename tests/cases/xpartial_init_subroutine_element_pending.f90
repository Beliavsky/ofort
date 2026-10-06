program partial_initialization
implicit none
real :: a(3)
call set_element(a(2), 7.0)
print *, a(2)
contains
subroutine set_element(x, value)
real, intent(out) :: x
real, intent(in) :: value
x = value
end subroutine set_element
end program partial_initialization
