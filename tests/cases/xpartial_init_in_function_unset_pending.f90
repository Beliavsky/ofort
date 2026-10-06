program partial_initialization_input
implicit none
real :: a(3)
call set_element(a(2))
print *, identity(a(1))
contains
subroutine set_element(x)
real, intent(out) :: x
x = 7.0
end subroutine set_element
real function identity(x) result(y)
real, intent(in) :: x
y = x
end function identity
end program partial_initialization_input
