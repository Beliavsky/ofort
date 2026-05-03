program xrrspacing
implicit none

integer, parameter :: n = 7

integer :: i
real :: a(n)

a = [-10.0, -1.0, -0.5, 0.0, 0.5, 1.0, 10.0]

print *, "rrspacing(x) returns the reciprocal of the relative spacing near x."
print *, "It is roughly abs(fraction(x)) * radix(x)**digits(x)."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i), " rrspacing(x) =", rrspacing(a(i))
end do
print *

print *, "kind examples:"
print *, "rrspacing(1.0)   =", rrspacing(1.0)
print *, "rrspacing(1.0_4) =", rrspacing(1.0_4)
print *, "rrspacing(1.0_8) =", rrspacing(1.0_8)
print *

print *, "nearby-value examples:"
print *, "rrspacing(1.0)              =", rrspacing(1.0)
print *, "rrspacing(nearest(1.0,1.0)) =", rrspacing(nearest(1.0,1.0))
print *, "rrspacing(2.0)              =", rrspacing(2.0)

end program xrrspacing
