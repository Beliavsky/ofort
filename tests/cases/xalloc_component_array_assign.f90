program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x(2), y(2)
allocate(x(1)%a(2), x(2)%a(3))
x(1)%a = [1, 2]
x(2)%a = [3, 4, 5]
y = x
x(1)%a = 99
x(2)%a = 88
print *, allocated(y(1)%a), size(y(1)%a), y(1)%a
print *, allocated(y(2)%a), size(y(2)%a), y(2)%a
end program main
