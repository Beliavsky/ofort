program partial_initialization_section_argument
implicit none
real :: a(4)
a(2:3) = [7.0, 9.0]
print *, inspect(a(1:2))
contains
integer function inspect(x) result(y)
real, intent(in) :: x(:)
y = size(x) + sum(shape(x))
end function inspect
end program partial_initialization_section_argument
