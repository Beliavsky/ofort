program xvector_subscript_2d_pending
implicit none
integer :: a(3,4), rows(2), cols(2), i
a = reshape([(i, i=1,12)], shape(a))
rows = [3, 1]
cols = [4, 2]
print *, a(rows, 2)
print *, a(2, cols)
end program xvector_subscript_2d_pending
