program xfraction
implicit none

integer, parameter :: n = 7

integer :: i
real :: a(n)

a = [-8.0, -3.5, -1.0, 0.0, 1.0, 3.5, 8.0]

print *, "fraction(x) returns the fractional part of the model representation of x."
print *, "x = fraction(x) * radix(x)**exponent(x), except when x is zero."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i), &
            " fraction(x) =", fraction(a(i)), &
            " exponent(x) =", exponent(a(i))
end do
print *

print *, "reconstruct nonzero values:"
do i = 1, n
   if (a(i) /= 0.0) then
      print *, "x =", a(i), &
               " reconstructed =", fraction(a(i)) * radix(a(i))**exponent(a(i))
   end if
end do
print *

print *, "real kind examples:"
print *, "fraction(3.5_4) =", fraction(3.5_4)
print *, "fraction(3.5_8) =", fraction(3.5_8)

end program xfraction
