program main
implicit none
integer, allocatable :: x(:)
allocate(x(-1:1))
x = [1, 2, 3]
print *, lbound(x), ubound(x), x
deallocate(x)
allocate(x(3:5))
x = [30, 40, 50]
print *, lbound(x), ubound(x), x(3), x(5)
end program main
