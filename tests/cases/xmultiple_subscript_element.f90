program xmultiple_subscript_element_pending
implicit none
integer :: a(3, 4)
integer :: i
a = reshape([(i, i=1,12)], shape(a))
print *, a(@[3, 2])
end program xmultiple_subscript_element_pending
