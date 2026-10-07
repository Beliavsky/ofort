program partial_initialization_inout
implicit none
real :: a(4)
a(2) = 5.0
a(4) = 9.0
call fill_middle(a(2:4))
print *, sum(a(2:4))
contains
subroutine fill_middle(x)
real, intent(inout) :: x(:)
x(2) = 7.0
end subroutine fill_middle
end program partial_initialization_inout
