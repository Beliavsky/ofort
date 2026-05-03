program xmerge
implicit none
integer, parameter :: n = 5
integer :: a(n), b(n), c(n)
logical :: tf(n)
integer :: x, y, z

a = [10, 20, 30, 40, 50]
b = [1, 2, 3, 4, 5]
tf = [.true., .false., .true., .false., .true.]

x = 10
y = 20
z = merge(x, y, .true.)
print *, "scalar, scalar, scalar:"
print *, z

c = merge(a, b, tf)
print *, "array, array, array:"
print *, c

c = merge(a, b, .false.)
print *, "array, array, scalar:"
print *, c

c = merge(100, b, tf)
print *, "scalar, array, array:"
print *, c

c = merge(a, -1, tf)
print *, "array, scalar, array:"
print *, c

c = merge(1, 0, tf)
print *, "scalar, scalar, array:"
print *, c

end program xmerge
