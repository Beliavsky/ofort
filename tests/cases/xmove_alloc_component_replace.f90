program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
allocate(x%a(3), y%a(2))
x%a = [1, 2, 3]
y%a = [7, 8]
call move_alloc(x%a, y%a)
print *, allocated(x%a), allocated(y%a), size(y%a), y%a
end program main
