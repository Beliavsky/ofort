program xscale
implicit none

integer, parameter :: n = 7

integer :: i
real :: a(n)

a = [-3.5, -1.0, -0.5, 0.0, 0.5, 1.0, 3.5]

print *, "scale(x, i) returns x * radix(x)**i."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i)
   print *, "  scale(x,  1) =", scale(a(i),  1)
   print *, "  scale(x, -1) =", scale(a(i), -1)
   print *, "  scale(x,  2) =", scale(a(i),  2)
end do
print *

print *, "kind examples:"
print *, "scale(1.5,   3) =", scale(1.5,   3)
print *, "scale(1.5_4, 3) =", scale(1.5_4, 3)
print *, "scale(1.5_8, 3) =", scale(1.5_8, 3)
print *

print *, "using exponent:"
do i = 1, n
   if (a(i) /= 0.0) then
      print *, "x =", a(i), &
               " exponent(x) =", exponent(a(i)), &
               " scale(fraction(x), exponent(x)) =", &
               scale(fraction(a(i)), exponent(a(i)))
   end if
end do

end program xscale
