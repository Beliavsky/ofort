program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
allocate(x%a(2))
x%a = [7, 8]
call clear(x%a)
print *, allocated(x%a)
contains
subroutine clear(a)
integer, allocatable, intent(inout) :: a(:)
deallocate(a)
end subroutine clear
end program main
