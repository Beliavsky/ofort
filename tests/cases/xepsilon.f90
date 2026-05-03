program xepsilon
implicit none

integer, parameter :: n = 4

real :: x
real :: a(n)

x = 1.0
a = [0.0, 1.0, 10.0, huge(0.0)]

print *, "epsilon(x) returns the smallest positive number e such that 1 + e > 1."
print *

print *, "default real examples:"
print *, "epsilon(1.0) =", epsilon(1.0)
print *, "epsilon(x)   =", epsilon(x)
print *

print *, "epsilon depends on kind, not value:"
print *, "epsilon(0.0)       =", epsilon(0.0)
print *, "epsilon(1.0)       =", epsilon(1.0)
print *, "epsilon(10.0)      =", epsilon(10.0)
print *, "epsilon(huge(0.0)) =", epsilon(huge(0.0))
print *

print *, "array element examples:"
print *, "a = ", a
print *, "epsilon(a(1)) =", epsilon(a(1))
print *, "epsilon(a(2)) =", epsilon(a(2))
print *, "epsilon(a(3)) =", epsilon(a(3))
print *, "epsilon(a(4)) =", epsilon(a(4))
print *

print *, "real kind examples:"
print *, "epsilon(1.0_4) =", epsilon(1.0_4)
print *, "epsilon(1.0_8) =", epsilon(1.0_8)

end program xepsilon
