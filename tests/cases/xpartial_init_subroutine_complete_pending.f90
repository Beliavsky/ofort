program partial_initialization
implicit none
real :: a(3)
call set_element(a(2), 7.0)
call set_element(a(1), 5.0)
call set_element(a(3), 9.0)
print *, sum(a)
contains
subroutine set_element(x, value)
real, intent(out) :: x
real, intent(in) :: value
x = value
end subroutine set_element
end program partial_initialization
