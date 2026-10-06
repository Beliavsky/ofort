program partial_initialization
implicit none
real :: a(3), y
! Expected: 21.0. All three elements are initialized individually.
y = set_element(a(2), 7.0)
y = set_element(a(1), 5.0)
y = set_element(a(3), 9.0)
print *, sum(a)
contains
real function set_element(x, value) result(r)
real, intent(out) :: x
real, intent(in) :: value
x = value
r = x
end function set_element
end program partial_initialization
