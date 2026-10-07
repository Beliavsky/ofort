program function_array_copyback
implicit none
real :: a(3), y, marker
marker = 11.0
a(1) = 5.0
a(3) = 9.0
y = fill(a)
print *, sum(a)
contains
real function fill(x) result(r)
real, intent(inout) :: x(:)
x(2) = 7.0
r = 0.0
end function fill
end program function_array_copyback
