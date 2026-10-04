program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x(2)
integer, target :: a(4)
a = [10, 20, 30, 40]
x(1)%p => a(2:4)
x(1)%p(2) = 99
print *, a
end program main
