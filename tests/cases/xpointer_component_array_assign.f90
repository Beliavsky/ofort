program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2), y(2)
integer, target :: a(3)
a = [1, 2, 3]
x(1)%p => a
y = x
a = [4, 5, 6]
print *, associated(y(1)%p), associated(y(2)%p), y(1)%p
end program main
