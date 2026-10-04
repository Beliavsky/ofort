program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(5)
a = [10, 20, 30, 40, 50]
x%p => a(2:4)
print *, associated(x%p, a(2:4)), associated(x%p, a), lbound(x%p), ubound(x%p)
end program main
