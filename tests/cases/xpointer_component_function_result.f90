program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
integer, target :: a(2)
type(t) :: x
a = [7, 8]
x = make(a)
a = [9, 10]
print *, associated(x%p), x%p
contains
function make(target) result(res)
integer, target, intent(inout) :: target(:)
type(t) :: res
res%p => target
end function make
end program main
