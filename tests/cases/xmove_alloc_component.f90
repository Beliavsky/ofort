program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
allocate(x%a(-1:1))
x%a = [10, 20, 30]
call move_alloc(x%a, y%a)
print *, allocated(x%a), allocated(y%a), lbound(y%a), ubound(y%a), y%a
end program main
