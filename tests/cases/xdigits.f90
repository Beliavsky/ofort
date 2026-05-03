program xdigits
implicit none

integer, parameter :: n = 4

integer :: i
integer :: a(n)
real :: x

a = [0, 1, -1, huge(0)]
x = 1.0

print *, "digits(x) returns the number of significant binary digits."
print *

print *, "integer examples:"
do i = 1, n
   print *, "a(i) =", a(i), " digits(a(i)) =", digits(a(i))
end do
print *

print *, "integer kind examples:"
print *, "digits(0)   =", digits(0)
print *, "digits(0_1) =", digits(0_1)
print *, "digits(0_2) =", digits(0_2)
print *, "digits(0_4) =", digits(0_4)
print *, "digits(0_8) =", digits(0_8)
print *

print *, "real examples:"
print *, "digits(1.0) =", digits(1.0)
print *, "digits(x)   =", digits(x)
print *

print *, "real kind examples:"
print *, "digits(1.0)    =", digits(1.0)
print *, "digits(1.0_4)  =", digits(1.0_4)
print *, "digits(1.0_8)  =", digits(1.0_8)

end program xdigits
