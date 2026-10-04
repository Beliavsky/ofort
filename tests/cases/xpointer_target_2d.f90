implicit none
integer, target :: m(3,4)
integer, pointer :: p(:,:)
integer :: i
m = reshape([(i, i=1,12)], [3,4])
p => m(2:,:)
print *, shape(p)
p = 99
p(1,2) = 77
print *, m(1,:)
print *, m(2,:)
print *, m(3,:)
end
