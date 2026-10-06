program partial_initialization_section_argument
implicit none
real :: a(4)
a(2:3) = [7.0, 9.0]
call inspect(a(1:2))
contains
subroutine inspect(x)
real, intent(in) :: x(:)
print *, sum(x)
end subroutine inspect
end program partial_initialization_section_argument
