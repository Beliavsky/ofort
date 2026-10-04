program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2)
integer, target :: a(5)
a = [10, 20, 30, 40, 50]
x(1)%p(0:) => a(2:4)
x(1)%p(1) = 99
print *, lbound(x(1)%p), ubound(x(1)%p), a
end program main
