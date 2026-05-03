program xibset
implicit none

integer, parameter :: n = 5
integer, parameter :: npos = 5

integer :: i, j
integer :: a(n)
integer :: pos(npos)

a   = [0, 1, 3, 10, 15]
pos = [0, 1, 2, 3, 4]

print *, "ibset(i, pos) returns i with bit pos set to 1."
print *, "Bit positions start at 0."
print *

do i = 1, n
   print *, "i =", a(i)
   do j = 1, npos
      print *, "  pos =", pos(j), " ibset =", ibset(a(i), pos(j))
   end do
   print *
end do

print *, "direct examples:"
print *, "ibset(10, 0) =", ibset(10, 0)
print *, "ibset(10, 1) =", ibset(10, 1)
print *, "ibset(10, 2) =", ibset(10, 2)
print *, "ibset(10, 3) =", ibset(10, 3)

end program xibset
