program main
implicit none
type :: t
   integer, pointer :: p => null()
end type t
type(t) :: x
integer, target :: a
a = 42
x%p => a
print *, associated(x%p), x%p
end program main
