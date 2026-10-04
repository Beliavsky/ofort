program xvector_subscript_expr_pending
implicit none
integer :: a(5), idx(3), i
a = [10, 20, 30, 40, 50]
idx = [1, 3, 5]
print *, a(idx + 0)
print *, a([(2*i-1, i=1,3)])
end program xvector_subscript_expr_pending
