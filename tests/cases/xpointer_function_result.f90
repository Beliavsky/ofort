program main
implicit none
integer, target :: a(3)
integer, pointer :: p(:)
a = [10, 20, 30]
p => get_pointer(a)
print *, associated(p), size(p), p
p(2) = 200
print *, a
contains
function get_pointer(x) result(q)
integer, target, intent(inout) :: x(:)
integer, pointer :: q(:)
q => x
end function get_pointer
end program main
