program main
implicit none
type :: t
   integer :: n
end type t
type(t) :: x
x%n = 5
print *, f(x)
contains
pure function f(a)
type(t), intent(in) :: a
integer :: f
a%n = 50
f = a%n
end function f
end program main
