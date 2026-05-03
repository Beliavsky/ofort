program xbits_more
implicit none

integer, parameter :: n = 5
integer, parameter :: nshift = 5

integer :: i
integer :: a(n)
integer :: b(n)
integer :: shifts(nshift)
integer :: from
integer :: to

a = [0, 1, 3, 10, 15]
b = [0, 1, 5, 12, 7]
shifts = [-2, -1, 0, 1, 2]

print *, "ieor(i,j) returns bitwise exclusive or."
print *, "ior(i,j)  returns bitwise inclusive or."
print *

do i = 1, n
   print *, "i =", a(i), " j =", b(i), &
            " ieor =", ieor(a(i), b(i)), &
            " ior =", ior(a(i), b(i))
end do

print *
print *, "ishft(i, shift) shifts bits."
print *, "positive shift moves left; negative shift moves right."
print *

do i = 1, n
   print *, "i =", a(i)
   print *, "  ishft(i,-2) =", ishft(a(i), -2)
   print *, "  ishft(i,-1) =", ishft(a(i), -1)
   print *, "  ishft(i, 0) =", ishft(a(i),  0)
   print *, "  ishft(i, 1) =", ishft(a(i),  1)
   print *, "  ishft(i, 2) =", ishft(a(i),  2)
end do

print *
print *, "ishftc(i, shift, size) circularly shifts the rightmost size bits."
print *

do i = 1, n
   print *, "i =", a(i)
   print *, "  ishftc(i, 1, 4)  =", ishftc(a(i),  1, 4)
   print *, "  ishftc(i, 2, 4)  =", ishftc(a(i),  2, 4)
   print *, "  ishftc(i,-1, 4)  =", ishftc(a(i), -1, 4)
   print *, "  ishftc(i,-2, 4)  =", ishftc(a(i), -2, 4)
end do

print *
print *, "mvbits(from, frompos, len, to, topos) copies bits from one integer to another."
print *, "The destination integer is modified."
print *

from = 10
to = 0
call mvbits(from, 1, 2, to, 0)
print *, "from = 10, to = 0"
print *, "call mvbits(from, 1, 2, to, 0)"
print *, "to =", to

from = 15
to = 0
call mvbits(from, 0, 4, to, 0)
print *, "from = 15, to = 0"
print *, "call mvbits(from, 0, 4, to, 0)"
print *, "to =", to

from = 10
to = 15
call mvbits(from, 1, 2, to, 2)
print *, "from = 10, to = 15"
print *, "call mvbits(from, 1, 2, to, 2)"
print *, "to =", to

from = 5
to = 8
call mvbits(from, 0, 3, to, 1)
print *, "from = 5, to = 8"
print *, "call mvbits(from, 0, 3, to, 1)"
print *, "to =", to

end program xbits_more
