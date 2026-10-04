program xpointer_dummy_section_out
implicit none
integer, target :: a(5)
integer, pointer :: p(:)

a = [10, 20, 30, 40, 50]
call set_section(p, a)
print *, associated(p), lbound(p), ubound(p), p
p = p * 10
print *, a

contains

subroutine set_section(x, a)
integer, pointer, intent(out) :: x(:)
integer, target, intent(inout) :: a(:)
x => a(2:4)
end subroutine set_section

end program xpointer_dummy_section_out
