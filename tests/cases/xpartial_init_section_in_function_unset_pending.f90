program partial_initialization_section_argument
implicit none
real :: a(4)
a(2:3) = [7.0, 9.0]
print *, inspect(a(1:2))
contains
real function inspect(x) result(y)
real, intent(in) :: x(:)
y = sum(x)
end function inspect
end program partial_initialization_section_argument
