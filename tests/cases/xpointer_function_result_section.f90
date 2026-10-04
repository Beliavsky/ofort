program main
implicit none
integer, target :: a(6)
integer, pointer :: p(:)
a = [10, 20, 30, 40, 50, 60]
p => get_pointer(a)
print *, associated(p), size(p), p
p(2) = 400
print *, a
contains
function get_pointer(x) result(q)
integer, target, intent(inout) :: x(:)
integer, pointer :: q(:)
q => x(2:6:2)
end function get_pointer
end program main
