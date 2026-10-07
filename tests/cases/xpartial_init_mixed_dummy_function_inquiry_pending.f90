program mixed_section_dummy
implicit none
real :: a(3)
a(2) = 7.0
print *, inspect(a(1:2))
contains
integer function inspect(x) result(y)
real, intent(in) :: x(:)
y = size(x) + sum(shape(x))
end function inspect
end program mixed_section_dummy
