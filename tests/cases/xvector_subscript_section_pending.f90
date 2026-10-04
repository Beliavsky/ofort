program xvector_subscript_section_pending
implicit none
integer :: a(6), idx(3)
a = [10, 20, 30, 40, 50, 60]
idx = [1, 3, 6]
print *, a(idx) + 1
print *, sum(a(idx))
end program xvector_subscript_section_pending
