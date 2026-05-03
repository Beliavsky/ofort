integer, allocatable :: p(:,:,:)
integer :: n1, n2, n3, n4, n5, n6
n1 = 0
n2 = 2
n3 = -1
n4 = 1
n5 = 3
n6 = 4
allocate(p(n1:n2,n3:n4,n5:n6))
p = 7
p(0,-1,3) = 11
p(2,1,4) = 13
print *, lbound(p)
print *, ubound(p)
print *, size(p), p(0,-1,3), p(1,0,3), p(2,1,4)
