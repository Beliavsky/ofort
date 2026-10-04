program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
allocate(y%a(2))
y%a = [7, 8]
call move_alloc(x%a, y%a)
print *, allocated(x%a), allocated(y%a)
end program main
