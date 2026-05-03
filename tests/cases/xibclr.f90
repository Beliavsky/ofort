program xibclr
implicit none

integer, parameter :: n = 5
integer, parameter :: npos = 5

integer :: i, j
integer :: a(n)
integer :: pos(npos)

a   = [0, 1, 3, 10, 15]
pos = [0, 1, 2, 3, 4]

print *, "ibclr(i, pos) returns i with bit pos cleared (set to 0)."
print *, "Bit positions start at 0."
print *

do i = 1, n
   print *, "i =", a(i)
   do j = 1, npos
      print *, "  pos =", pos(j), " ibclr =", ibclr(a(i), pos(j))
   end do
   print *
end do

print *, "direct examples:"
print *, "ibclr(10, 1) =", ibclr(10, 1)
print *, "ibclr(10, 3) =", ibclr(10, 3)
print *, "ibclr(15, 0) =", ibclr(15, 0)
print *, "ibclr(15, 3) =", ibclr(15, 3)

end program xibclr
