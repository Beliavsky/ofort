program xassociated_component_section_target
implicit none

type box
   integer, pointer :: q(:)
end type box

type(box) :: b
integer, target :: a(5)
integer, pointer :: p(:)

a = [10, 20, 30, 40, 50]
b%q => a
p => b%q(2:4)
print *, associated(p, a(2:4))
print *, associated(p, b%q(2:4))
print *, associated(p, b%q(1:3))

end program xassociated_component_section_target
