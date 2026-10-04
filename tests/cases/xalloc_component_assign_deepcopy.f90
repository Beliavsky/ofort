program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
allocate(x%a(3))
x%a = [1, 2, 3]
y = x
x%a = 99
print *, allocated(y%a), size(y%a), y%a
end program main
