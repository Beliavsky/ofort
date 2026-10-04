program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(-2:2)
a = [10, 20, 30, 40, 50]
x%p => a
print *, lbound(x%p), ubound(x%p), x%p(-2), x%p(2)
end program main
