program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x(2)
allocate(x(2)%a(2))
x(2)%a = [7, 8]
call show(x(2))
contains
subroutine show(arg)
type(t), intent(in) :: arg
print *, allocated(arg%a), size(arg%a), arg%a
end subroutine show
end program main
