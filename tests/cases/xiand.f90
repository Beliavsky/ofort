program xiand
implicit none

integer, parameter :: n = 6

integer :: i
integer :: a(n)
integer :: b(n)

a = [0, 1, 2, 3, 10, 15]
b = [0, 1, 1, 2, 12,  5]

print *, "iand(i, j) returns the bitwise logical and of integers i and j."
print *

do i = 1, n
   print *, "i =", a(i), " j =", b(i), " iand(i,j) =", iand(a(i), b(i))
end do
print *

print *, "direct examples:"
print *, "iand(10, 12) =", iand(10, 12)
print *, "iand(15,  5) =", iand(15,  5)
print *, "iand( 7,  3) =", iand( 7,  3)
print *, "iand( 8,  1) =", iand( 8,  1)

end program xiand
