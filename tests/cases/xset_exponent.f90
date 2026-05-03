program xset_exponent
implicit none

integer, parameter :: n = 7

integer :: i
real :: a(n)

a = [-3.5, -1.0, -0.5, 0.0, 0.5, 1.0, 3.5]

print *, "set_exponent(x, i) returns a real with fraction(x) and exponent i."
print *, "It is like fraction(x) * radix(x)**i."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i)
   print *, "  fraction(x)        =", fraction(a(i))
   print *, "  exponent(x)        =", exponent(a(i))
   print *, "  set_exponent(x, 0) =", set_exponent(a(i), 0)
   print *, "  set_exponent(x, 1) =", set_exponent(a(i), 1)
   print *, "  set_exponent(x, 2) =", set_exponent(a(i), 2)
end do
print *

print *, "kind examples:"
print *, "set_exponent(1.5,   3) =", set_exponent(1.5,   3)
print *, "set_exponent(1.5_4, 3) =", set_exponent(1.5_4, 3)
print *, "set_exponent(1.5_8, 3) =", set_exponent(1.5_8, 3)

end program xset_exponent
