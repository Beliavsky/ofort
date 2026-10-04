program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2)
integer, target :: a(2)
a = [3, 4]
x(1)%p => a
nullify(x(1)%p)
print *, associated(x(1)%p), associated(x(2)%p)
end program main
