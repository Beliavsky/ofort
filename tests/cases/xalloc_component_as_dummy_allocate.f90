program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
call fill(x%a)
print *, allocated(x%a), size(x%a), x%a
contains
subroutine fill(a)
integer, allocatable, intent(inout) :: a(:)
allocate(a(3))
a = [1, 2, 3]
end subroutine fill
end program main
