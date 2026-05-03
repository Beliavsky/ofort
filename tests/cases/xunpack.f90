program xunpack
implicit none

integer :: vector(6)
integer :: field1(6)
integer :: field2(2,3)
integer :: result1(6)
integer :: result2(2,3)
integer :: i

vector = [10, 20, 30, 40, 50, 60]
field1 = [-1, -1, -1, -1, -1, -1]

field2(:,1) = [-1, -2]
field2(:,2) = [-3, -4]
field2(:,3) = [-5, -6]

print *, "vector = ", vector
print *

result1 = unpack(vector, [ .true., .false., .true., .false., .true., .false. ], field1)
print *, "1-d unpack:"
print *, result1
print *

result1 = unpack(vector, vector > 30, 0)
print *, "scalar field, field = 0:"
print *, result1
print *

print *, "2-d field:"
do i = 1, size(field2, 1)
   print *, field2(i,:)
end do
print *

result2 = unpack(vector, field2 < -3, field2)
print *, "2-d unpack, mask = field2 < -3:"
do i = 1, size(result2, 1)
   print *, result2(i,:)
end do
print *

result1 = unpack([100, 200, 300], &
                 [ .true., .false., .true., .false., .true., .false. ], &
                 field1)
print *, "vector has exactly count(mask) elements:"
print *, result1
print *

result1 = unpack([777], &
                 [ .false., .false., .false., .false., .false., .false. ], &
                 field1)
print *, "mask all false, vector is not used:"
print *, result1

end program xunpack
