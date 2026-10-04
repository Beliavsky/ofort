program xassociated_section_remap_target
implicit none
integer, target :: a(5)
integer, pointer :: p(:)

a = [10, 20, 30, 40, 50]
p(0:) => a(2:4)
print *, lbound(p), ubound(p)
print *, associated(p, a(2:4))
print *, associated(p, a(1:3))

end program xassociated_section_remap_target
