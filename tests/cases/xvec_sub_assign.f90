program main
implicit none
real :: x(5)
x = -1.0
x([2,3,5]) = 10.0
print *, x
x([2,3,5]) = [10.0, 20.0, 30.0]
print *, x
end program main
