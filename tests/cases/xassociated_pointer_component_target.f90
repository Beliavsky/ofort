program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(3), b(3)
a = [1, 2, 3]
b = [4, 5, 6]
x%p => a
print *, associated(x%p, a), associated(x%p, b)
x%p => b
print *, associated(x%p, a), associated(x%p, b)
end program main
