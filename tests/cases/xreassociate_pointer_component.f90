program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(2), b(3)
a = [1, 2]
b = [3, 4, 5]
x%p => a
nullify(x%p)
x%p => b
print *, associated(x%p), size(x%p), x%p
end program main
