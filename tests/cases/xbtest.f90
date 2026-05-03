program xbtest
implicit none

integer, parameter :: n = 5
integer, parameter :: npos = 6

integer :: i, j
integer :: a(n)
integer :: pos(npos)

a = [0, 1, 2, 3, 10]
pos = [0, 1, 2, 3, 4, 5]

print *, "btest(i, pos) is true if bit pos of integer i is 1."
print *, "Bit positions start at 0."
print *

do i = 1, n
   print *, "i =", a(i)
   do j = 1, npos
      print *, "  pos =", pos(j), " btest =", btest(a(i), pos(j))
   end do
   print *
end do

print *, "some direct examples:"
print *, "btest(10, 0) =", btest(10, 0)
print *, "btest(10, 1) =", btest(10, 1)
print *, "btest(10, 2) =", btest(10, 2)
print *, "btest(10, 3) =", btest(10, 3)

end program xbtest
