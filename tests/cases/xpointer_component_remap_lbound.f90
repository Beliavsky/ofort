program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(5)
a = [10, 20, 30, 40, 50]
x%p(0:) => a(2:4)
print *, lbound(x%p), ubound(x%p), size(x%p), x%p(0), x%p(2)
end program main
