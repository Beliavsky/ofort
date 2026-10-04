program xpointer_dummy_component_out
implicit none

type box
   integer, pointer :: value
end type box

type(box) :: b
integer, target :: t
integer, pointer :: p

t = 42
b%value => t
call set_component(p, b)
print *, associated(p), p
p = 99
print *, t

contains

subroutine set_component(x, b)
integer, pointer, intent(out) :: x
type(box), intent(inout) :: b
x => b%value
end subroutine set_component

end program xpointer_dummy_component_out
