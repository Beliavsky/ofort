program forwarded_mixed_array
implicit none
real :: a(3)
a(2) = 7.0
call outer(a(1:2))
contains
subroutine outer(x)
real, intent(in) :: x(:)
print *, inner(x)
end subroutine outer
real function inner(x) result(y)
real, intent(in) :: x(:)
y = sum(x)
end function inner
end program forwarded_mixed_array
