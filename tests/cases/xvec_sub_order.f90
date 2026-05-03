program main
implicit none
real :: x(3) = [10.0, 20.0, 30.0]
x([1, 2]) = x([2, 1])
print *, x
x([1, 2]) = -1.0
print *, x
end program main
