program xbit_size
implicit none

integer, parameter :: n = 4

integer :: i
integer :: a(n)

a = [0, 1, -1, huge(0)]

print *, "bit_size returns the number of bits used to represent an integer."
print *

print *, "bit_size(0)       =", bit_size(0)
print *, "bit_size(0_1)     =", bit_size(0_1)
print *, "bit_size(0_2)     =", bit_size(0_2)
print *, "bit_size(0_4)     =", bit_size(0_4)
print *, "bit_size(0_8)     =", bit_size(0_8)
print *

print *, "scalar examples:"
do i = 1, n
   print *, "a(i) =", a(i), " bit_size(a(i)) =", bit_size(a(i))
end do
print *

print *, "huge examples:"
print *, "huge(0)   =", huge(0),   " bit_size =", bit_size(huge(0))
print *, "huge(0_1) =", huge(0_1), " bit_size =", bit_size(huge(0_1))
print *, "huge(0_2) =", huge(0_2), " bit_size =", bit_size(huge(0_2))
print *, "huge(0_4) =", huge(0_4), " bit_size =", bit_size(huge(0_4))
print *, "huge(0_8) =", huge(0_8), " bit_size =", bit_size(huge(0_8))

end program xbit_size
