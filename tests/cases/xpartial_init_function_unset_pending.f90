program partial_initialization
implicit none
real :: a(3), y
! Must report an unset element when a(1) is read.
y = set_element(a(2), 7.0)
print *, a(1)
contains
real function set_element(x, value) result(r)
real, intent(out) :: x
real, intent(in) :: value
x = value
r = x
end function set_element
end program partial_initialization
