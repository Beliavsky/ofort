program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(2)
a = [1, 2]
x%p => a
x%p => null()
print *, associated(x%p)
end program main
