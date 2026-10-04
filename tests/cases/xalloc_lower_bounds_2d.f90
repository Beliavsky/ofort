program main
implicit none
integer, allocatable :: x(:,:)
allocate(x(0:1, -1:1))
x = reshape([1, 2, 3, 4, 5, 6], shape(x))
print *, lbound(x), ubound(x), shape(x)
print *, x(0,-1), x(1,-1), x(0,0), x(1,1)
deallocate(x)
end program main
