program xpack
implicit none

integer :: a(6)
integer :: b(2,3)
integer, allocatable :: p(:)
integer :: i

a = [1, 2, 3, 4, 5, 6]

b(:,1) = [1, 2]
b(:,2) = [3, 4]
b(:,3) = [5, 6]

print *, "a = ", a
print *

p = pack(a, a > 3)
print *, "pack(a, a > 3) = ", p

p = pack(a, mod(a, 2) == 0)
print *, "pack(a, even mask) = ", p

p = pack(a, .true.)
print *, "pack(a, scalar .true.) = ", p

print *
print *, "b:"
do i = 1, size(b,1)
   print *, b(i,:)
end do

p = pack(b, b >= 3)
print *, "pack(b, b >= 3) = ", p

print *
print *, "pack with vector argument:"
p = pack(a, a > 4, [100, 200, 300, 400, 500, 600])
print *, p

print *
print *, "empty result when no mask values are true:"
p = pack(a, a > 99)
print *, "size(pack(a, a > 99)) =", size(p)

end program xpack
