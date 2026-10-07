program forwarded_mixed_array
implicit none
real :: a(3)
a(2) = 7.0
call outer(a(1:2))
contains
subroutine outer(x)
real, intent(in) :: x(:)
call inner(x)
end subroutine outer
subroutine inner(x)
real, intent(in) :: x(:)
print *, x(1)
end subroutine inner
end program forwarded_mixed_array
