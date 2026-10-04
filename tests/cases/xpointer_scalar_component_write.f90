program main
implicit none
type :: t
   integer, pointer :: p => null()
end type t
type(t) :: x
integer, target :: a
a = 10
x%p => a
x%p = 99
print *, a, x%p
end program main
