program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
allocate(x%a(2))
x%a = [7, 8]
call resize(x%a)
print *, allocated(x%a), size(x%a), x%a
contains
subroutine resize(a)
integer, allocatable, intent(inout) :: a(:)
deallocate(a)
allocate(a(4))
a = [1, 2, 3, 4]
end subroutine resize
end program main
