program partial_initialization_inout
implicit none
real :: a(4)
a(1) = 5.0
call fill_middle(a)
print *, a(1), a(2)
contains
subroutine fill_middle(x)
real, intent(inout) :: x(:)
x(2) = 7.0
end subroutine fill_middle
end program partial_initialization_inout
