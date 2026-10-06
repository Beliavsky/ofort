program partial_initialization_input
implicit none
real :: a(3)
call set_element(a(2))
call inspect(a(1))
contains
subroutine set_element(x)
real, intent(out) :: x
x = 7.0
end subroutine set_element
subroutine inspect(x)
real, intent(in) :: x
print *, x
end subroutine inspect
end program partial_initialization_input
