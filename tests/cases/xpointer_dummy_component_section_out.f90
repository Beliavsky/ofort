program xpointer_dummy_component_section_out
implicit none

type box
   integer, pointer :: a(:)
end type box

type(box) :: b
integer, target :: t(5)
integer, pointer :: p(:)

t = [10, 20, 30, 40, 50]
b%a => t
call set_component_section(p, b)
print *, associated(p), lbound(p), ubound(p), p
p = p * 10
print *, t

contains

subroutine set_component_section(x, b)
integer, pointer, intent(out) :: x(:)
type(box), intent(inout) :: b
x => b%a(2:4)
end subroutine set_component_section

end program xpointer_dummy_component_section_out
