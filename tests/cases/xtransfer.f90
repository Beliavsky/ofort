program xtransfer
implicit none

integer, parameter :: n = 4

integer :: i
integer :: ia(n)
real :: ra(n)
character(len=4) :: s
integer :: i_from_chars
real :: r
integer :: i_from_real
real :: r_from_int

ia = [1, 2, 3, 4]
ra = [1.0, 2.0, 3.0, 4.0]

print *, "transfer(source, mold) copies the bit pattern of source into the type of mold."
print *

! integer -> real
print *, "integer to real:"
do i = 1, n
   r_from_int = transfer(ia(i), 0.0)
   print *, "ia(i) =", ia(i), " transfer -> real =", r_from_int
end do
print *

! real -> integer
print *, "real to integer:"
do i = 1, n
   i_from_real = transfer(ra(i), 0)
   print *, "ra(i) =", ra(i), " transfer -> integer =", i_from_real
end do
print *

! character -> integer
s = "ABCD"
i_from_chars = transfer(s, 0)
print *, "character to integer:"
print *, "s =", s, " transfer(s,0) =", i_from_chars
print *

! integer -> character
s = transfer(ia, s)
print *, "integer array to character:"
print *, "ia =", ia
print *, "transfer(ia, s) =", s
print *

! array result (size argument)
print *, "array result using size argument:"
print *, "transfer(ia, 0.0, size=2) =", transfer(ia, 0.0, size=2)
print *

! partial reinterpretation
print *, "partial reinterpretation:"
print *, "transfer(ia, 0.0, size=1) =", transfer(ia, 0.0, size=1)

end program xtransfer
