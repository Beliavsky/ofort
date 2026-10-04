program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x(2)
allocate(x(1)%a(2))
x(1)%a = [4, 5]
call move_alloc(x(1)%a, x(2)%a)
print *, allocated(x(1)%a), allocated(x(2)%a), size(x(2)%a), x(2)%a
end program main
