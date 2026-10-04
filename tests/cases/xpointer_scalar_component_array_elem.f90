program main
implicit none
type :: t
   integer, pointer :: p => null()
end type t
type(t) :: x(2)
integer, target :: a
a = 7
x(1)%p => a
x(1)%p = 8
print *, associated(x(1)%p), associated(x(2)%p), a, x(1)%p
end program main
