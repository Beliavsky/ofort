program main
implicit none
integer, allocatable :: x(:)
allocate(x(-2:2))
x = [10, 20, 30, 40, 50]
print *, lbound(x), ubound(x), size(x)
print *, x(-2), x(0), x(2)
deallocate(x)
end program main
