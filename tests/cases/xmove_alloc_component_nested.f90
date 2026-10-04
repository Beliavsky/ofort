program main
implicit none
type :: inner
   integer, allocatable :: a(:)
end type inner
type :: outer
   type(inner) :: child
end type outer
type(outer) :: x, y
allocate(x%child%a(2))
x%child%a = [4, 5]
call move_alloc(x%child%a, y%child%a)
print *, allocated(x%child%a), allocated(y%child%a), size(y%child%a), y%child%a
end program main
