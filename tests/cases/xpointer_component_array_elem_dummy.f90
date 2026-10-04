program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2)
integer, target :: a(2)
a = [7, 8]
x(2)%p => a
call show(x(2))
contains
subroutine show(arg)
type(t), intent(in) :: arg
print *, associated(arg%p), size(arg%p), arg%p
end subroutine show
end program main
