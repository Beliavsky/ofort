program main
implicit none
type :: t
   integer, pointer :: p => null()
end type t
type(t) :: x
integer, target :: a, b
a = 1
b = 2
x%p => a
print *, associated(x%p, a), associated(x%p, b)
x%p => b
print *, associated(x%p, a), associated(x%p, b)
end program main
