program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2)
integer, target :: a(4)
a = [10, 20, 30, 40]
x(1)%p => a(2:4)
print *, associated(x(1)%p), associated(x(2)%p), size(x(1)%p), x(1)%p
end program main
