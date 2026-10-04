program main
implicit none
integer, allocatable :: x(:), y(:)
allocate(x(-2:0))
x = [7, 8, 9]
allocate(y, mold=x)
y = [70, 80, 90]
print *, lbound(y), ubound(y), y
end program main
