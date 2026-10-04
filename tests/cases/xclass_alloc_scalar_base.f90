program main
implicit none
type :: base
   integer :: i
end type base
class(base), allocatable :: x
allocate(base :: x)
x%i = 42
print *, allocated(x), x%i
end program main
