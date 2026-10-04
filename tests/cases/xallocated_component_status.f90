program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x, y
print *, allocated(x%a)
allocate(x%a(2))
print *, allocated(x%a)
call move_alloc(x%a, y%a)
print *, allocated(x%a), allocated(y%a)
deallocate(y%a)
print *, allocated(y%a)
end program main
