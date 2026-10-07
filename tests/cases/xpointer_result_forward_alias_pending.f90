program xpointer_result_forward_alias_pending
implicit none
integer, target :: a(8)
integer, pointer :: p(:), q(:)
a = [1, 2, 3, 4, 5, 6, 7, 8]
p => get_pointer(a)
q(0:) => p(3:1:-1)
q = [80, 60, 40]
print *, a
call update(p(1:2))
print *, a
print *, p, q
contains
function get_pointer(x) result(result)
integer, target, intent(inout) :: x(:)
integer, pointer :: result(:)
result(0:) => x(2:8:2)
end function get_pointer
subroutine update(x)
integer, intent(inout) :: x(:)
x = x + 100
end subroutine update
end program xpointer_result_forward_alias_pending
