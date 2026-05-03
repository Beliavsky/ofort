integer, parameter :: c(*,*) = reshape([1,2,3,4,5,6], [2,3])
integer :: n
integer, parameter :: d(*,*) = reshape([(n,n=1,6)], [2,3])
print *, shape(c)
print *, c
print *, shape(d)
print *, d
end
