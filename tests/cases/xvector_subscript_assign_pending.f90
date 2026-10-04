program xvector_subscript_assign_pending
implicit none
integer :: a(5), idx(3)
a = [10, 20, 30, 40, 50]
idx = [5, 1, 3]
a(idx) = [1, 2, 3]
print *, a
end program xvector_subscript_assign_pending
