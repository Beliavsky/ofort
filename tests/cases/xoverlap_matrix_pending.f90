program xoverlap_matrix_pending
implicit none
integer :: a(3,3), i
a = reshape([(i, i=1,9)], [3,3])
a = transpose(a)
print *, a
a = reshape([(i, i=1,9)], [3,3])
a(:,2:3) = a(:,1:2)
print *, a
a = reshape([(i, i=1,9)], [3,3])
a([3,1],:) = a([1,3],:)
print *, a
end program xoverlap_matrix_pending
