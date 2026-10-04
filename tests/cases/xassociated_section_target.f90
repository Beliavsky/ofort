program xassociated_section_target
implicit none
integer, target :: a(5)
integer, pointer :: p(:)

a = [10, 20, 30, 40, 50]
p => a(2:4)
print *, associated(p)
print *, associated(p, a(2:4))
print *, associated(p, a(1:3))
print *, associated(p, a(2:5))

end program xassociated_section_target
