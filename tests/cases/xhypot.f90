real, parameter :: x = 3.0
real, parameter :: y = 4.0
real, parameter :: r = hypot(x, y)
real :: a(2), b(2)
a = [3.0, 5.0]
b = [4.0, 12.0]
print *, r
print *, hypot(a, b)
print *, hypot(a, 4.0)
end
