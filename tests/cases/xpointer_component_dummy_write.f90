program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(2)
a = [4, 5]
x%p => a
call bump(x)
print *, a
contains
subroutine bump(arg)
type(t), intent(inout) :: arg
arg%p(2) = 99
end subroutine bump
end program main
