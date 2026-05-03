program main
implicit none
real, allocatable :: x(:), y(:), z(:)
x = [10.0, 20.0]
print*,x
deallocate (x)
allocate (x(4), source = 100.0)
print*,x
allocate (y, mold=x)
y = -1.0
print*,y
z = 10 * y
print*,z
end program main
