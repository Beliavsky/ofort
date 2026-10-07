program partial_initialization_inout
implicit none
real :: a(3)
a(1) = 5.0
a(3) = 9.0
call fill_middle(a)
print *, sum(a)
contains
subroutine fill_middle(x)
real, intent(inout) :: x(:)
x(2) = 7.0
end subroutine fill_middle
end program partial_initialization_inout
