program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(2)
a = [4, 5]
x%p => a
call detach(x)
print *, associated(x%p)
contains
subroutine detach(arg)
type(t), intent(inout) :: arg
nullify(arg%p)
end subroutine detach
end program main
