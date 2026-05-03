program xprecision
implicit none

integer, parameter :: n = 4

integer :: i
real :: a(n)

a = [0.0, 1.0, -1.0, 100.0]

print *, "precision(x) returns the decimal precision of a real or complex kind."
print *

print *, "default real examples:"
do i = 1, n
   print *, "a(i) =", a(i), " precision(a(i)) =", precision(a(i))
end do
print *

print *, "real kind examples:"
print *, "precision(1.0)   =", precision(1.0)
print *, "precision(1.0_4) =", precision(1.0_4)
print *, "precision(1.0_8) =", precision(1.0_8)
print *

print *, "complex examples:"
print *, "precision((1.0, 2.0))     =", precision((1.0, 2.0))
print *, "precision((1.0_4, 2.0_4)) =", precision((1.0_4, 2.0_4))
print *, "precision((1.0_8, 2.0_8)) =", precision((1.0_8, 2.0_8))

end program xprecision
