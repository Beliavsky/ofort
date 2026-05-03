program xmaskl_maskr
implicit none

integer, parameter :: n = 6

integer :: i
integer :: bits(n)
integer :: full_mask

bits = [0, 1, 2, 4, 8, bit_size(0)]

print *, "maskl(i) returns an integer with the leftmost i bits set to 1."
print *, "maskr(i) returns an integer with the rightmost i bits set to 1."
print *

full_mask = maskr(bit_size(0))

print *, "bit_size(0) =", bit_size(0)
print *, "full mask   =", full_mask
print *

do i = 1, n
   print *, "i =", bits(i)
   print *, "  maskl(i) =", maskl(bits(i))
   print *, "  maskr(i) =", maskr(bits(i))
   print *
end do

print *, "using masks with iand:"
print *, "iand(15, maskr(1)) =", iand(15, maskr(1))
print *, "iand(15, maskr(2)) =", iand(15, maskr(2))
print *, "iand(15, maskr(3)) =", iand(15, maskr(3))
print *, "iand(15, maskr(4)) =", iand(15, maskr(4))
print *

print *, "left-mask examples depend on the integer bit size:"
print *, "maskl(1) =", maskl(1)
print *, "maskl(2) =", maskl(2)
print *, "maskl(3) =", maskl(3)
print *, "maskl(4) =", maskl(4)

end program xmaskl_maskr
