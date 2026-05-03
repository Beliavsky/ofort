program xibits
implicit none

integer, parameter :: n = 5

integer :: i
integer :: a(n)

a = [0, 1, 3, 10, 15]

print *, "ibits(i, pos, len) extracts len bits from i, starting at bit pos."
print *, "Bit positions start at 0."
print *

do i = 1, n
   print *, "i =", a(i)
   print *, "  ibits(i, 0, 1) =", ibits(a(i), 0, 1)
   print *, "  ibits(i, 0, 2) =", ibits(a(i), 0, 2)
   print *, "  ibits(i, 1, 2) =", ibits(a(i), 1, 2)
   print *, "  ibits(i, 2, 2) =", ibits(a(i), 2, 2)
   print *
end do

print *, "direct examples:"
print *, "ibits(10, 0, 1) =", ibits(10, 0, 1)
print *, "ibits(10, 1, 2) =", ibits(10, 1, 2)
print *, "ibits(15, 0, 4) =", ibits(15, 0, 4)
print *, "ibits(15, 2, 2) =", ibits(15, 2, 2)

end program xibits
