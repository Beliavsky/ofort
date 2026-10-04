program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x(2)
call fill(x(2)%a)
print *, allocated(x(1)%a), allocated(x(2)%a), size(x(2)%a), x(2)%a
contains
subroutine fill(a)
integer, allocatable, intent(inout) :: a(:)
allocate(a(2))
a = [9, 10]
end subroutine fill
end program main
