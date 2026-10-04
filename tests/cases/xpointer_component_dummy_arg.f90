program main
implicit none
type :: holder
   integer, pointer :: p(:)
end type holder
type(holder) :: h
integer, target :: a(3)
a = [10, 20, 30]
call set_component(a, h)
print *, associated(h%p), size(h%p), h%p
h%p(2) = 200
print *, a
contains
subroutine set_component(x, h)
integer, target, intent(inout) :: x(:)
type(holder), intent(inout) :: h
h%p => x
end subroutine set_component
end program main
