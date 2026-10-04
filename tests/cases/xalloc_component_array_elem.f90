program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x(2)
allocate(x(1)%a(3))
x(1)%a = [1, 2, 3]
print *, allocated(x(1)%a), allocated(x(2)%a), size(x(1)%a), x(1)%a
end program main
