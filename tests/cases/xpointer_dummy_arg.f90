program main
implicit none
integer, target :: a(3)
integer, pointer :: p(:)
a = [10, 20, 30]
call set_pointer(a, p)
print *, associated(p), size(p), p
p(2) = 200
print *, a
contains
subroutine set_pointer(x, q)
integer, target, intent(inout) :: x(:)
integer, pointer :: q(:)
q => x
end subroutine set_pointer
end program main
