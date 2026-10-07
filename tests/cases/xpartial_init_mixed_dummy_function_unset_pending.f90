program mixed_section_dummy
implicit none
real :: a(3)
a(2) = 7.0
print *, inspect(a(1:2))
contains
real function inspect(x) result(y)
real, intent(in) :: x(:)
y = x(1)
end function inspect
end program mixed_section_dummy
