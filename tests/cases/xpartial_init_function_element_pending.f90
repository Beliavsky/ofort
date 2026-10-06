program partial_initialization
implicit none
real :: a(3), y
! Expected: 7.0. Reading the element just initialized is valid.
y = set_element(a(2), 7.0)
print *, a(2)
contains
real function set_element(x, value) result(r)
real, intent(out) :: x
real, intent(in) :: value
x = value
r = x
end function set_element
end program partial_initialization
