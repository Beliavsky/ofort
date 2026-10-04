program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
allocate(x%a(2), y%a(3))
x%a = [1, 2]
y%a = [7, 8, 9]
print *, allocated(x%a), allocated(y%a)
y = x
print *, allocated(x%a), allocated(y%a), size(y%a)
deallocate(x%a)
y = x
print *, allocated(x%a), allocated(y%a)
end program main
