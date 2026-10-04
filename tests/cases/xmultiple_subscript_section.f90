program xmultiple_subscript_section_pending
implicit none
integer :: a(4, 5)
integer :: i
a = reshape([(i, i=1,20)], shape(a))
print *, shape(a(@[2, 3]:[4, 5]))
print *, a(@[2, 3]:[4, 5])
end program xmultiple_subscript_section_pending
