program main
implicit none
integer, target :: a(6)
integer, pointer :: p(:)
a = [10, 20, 30, 40, 50, 60]
call set_pointer(a, p)
print *, associated(p), size(p), p
p(2) = 400
print *, a
contains
subroutine set_pointer(x, q)
integer, target, intent(inout) :: x(:)
integer, pointer :: q(:)
q => x(2:6:2)
end subroutine set_pointer
end program main
