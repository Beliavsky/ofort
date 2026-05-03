program xrange
implicit none

integer, parameter :: n_int = 4
integer, parameter :: n_real = 4

integer :: i
integer :: ia(n_int)
real :: ra(n_real)

ia = [0, 1, -1, 100]
ra = [0.0, 1.0, -1.0, 100.0]

print *, "range(x) returns the decimal exponent range of x."
print *

print *, "integer examples:"
do i = 1, n_int
   print *, "ia(i) =", ia(i), " range(ia(i)) =", range(ia(i))
end do
print *

print *, "integer kind examples:"
print *, "range(0)   =", range(0)
print *, "range(0_1) =", range(0_1)
print *, "range(0_2) =", range(0_2)
print *, "range(0_4) =", range(0_4)
print *, "range(0_8) =", range(0_8)
print *

print *, "real examples:"
do i = 1, n_real
   print *, "ra(i) =", ra(i), " range(ra(i)) =", range(ra(i))
end do
print *

print *, "real kind examples:"
print *, "range(1.0)   =", range(1.0)
print *, "range(1.0_4) =", range(1.0_4)
print *, "range(1.0_8) =", range(1.0_8)
print *

print *, "complex examples:"
print *, "range((1.0, 2.0))     =", range((1.0, 2.0))
print *, "range((1.0_4, 2.0_4)) =", range((1.0_4, 2.0_4))
print *, "range((1.0_8, 2.0_8)) =", range((1.0_8, 2.0_8))

end program xrange
