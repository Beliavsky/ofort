program xnearest
implicit none

integer, parameter :: n = 5

integer :: i
real :: a(n)

a = [-1.0, 0.0, 1.0, 10.0, huge(1.0)]

print *, "nearest(x, s) returns the nearest representable number to x"
print *, "in the direction of the sign of s."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i)
   print *, "  nearest(x,  1.0) =", nearest(a(i),  1.0)
   print *, "  nearest(x, -1.0) =", nearest(a(i), -1.0)
end do
print *

print *, "kind examples:"
print *, "nearest(1.0_4,  1.0_4) =", nearest(1.0_4,  1.0_4)
print *, "nearest(1.0_4, -1.0_4) =", nearest(1.0_4, -1.0_4)
print *

print *, "nearest(1.0_8,  1.0_8) =", nearest(1.0_8,  1.0_8)
print *, "nearest(1.0_8, -1.0_8) =", nearest(1.0_8, -1.0_8)

end program xnearest
