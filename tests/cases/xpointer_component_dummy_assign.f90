program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(3)
a = [1, 2, 3]
call attach(x, a)
print *, associated(x%p), size(x%p), x%p
contains
subroutine attach(arg, target)
type(t), intent(inout) :: arg
integer, target, intent(inout) :: target(:)
arg%p => target
end subroutine attach
end program main
