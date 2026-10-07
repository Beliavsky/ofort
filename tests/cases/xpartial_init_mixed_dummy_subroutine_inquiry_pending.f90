program mixed_section_dummy
implicit none
real :: a(3)
a(2) = 7.0
call inspect(a(1:2))
contains
subroutine inspect(x)
real, intent(in) :: x(:)
print *, size(x), shape(x)
end subroutine inspect
end program mixed_section_dummy
