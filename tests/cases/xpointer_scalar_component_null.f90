program main
implicit none
type :: t
   integer, pointer :: p => null()
end type t
type(t) :: x
integer, target :: a
a = 1
x%p => a
nullify(x%p)
print *, associated(x%p)
x%p => a
x%p => null()
print *, associated(x%p)
end program main
