program xoverlap_vector_pending
implicit none
integer :: a(6), indices(3)
a = [1, 2, 3, 4, 5, 6]
indices = [3, 1, 2]
a(indices) = a(1:3)
print *, a
a = [1, 2, 3, 4, 5, 6]
a(1:3) = a(indices)
print *, a
a = [2, 3, 1, 6, 4, 5]
a(a) = a
print *, a
end program xoverlap_vector_pending
