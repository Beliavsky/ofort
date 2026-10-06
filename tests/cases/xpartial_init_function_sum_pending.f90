program partial_initialization
implicit none
real :: a(3), y
! Must report unset elements when the whole array is reduced.
y = set_element(a(2), 7.0)
print *, sum(a)
contains
real function set_element(x, value) result(r)
real, intent(out) :: x
real, intent(in) :: value
x = value
r = x
end function set_element
end program partial_initialization
