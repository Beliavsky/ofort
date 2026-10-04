program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
allocate(x%a(3))
call show(x)
contains
subroutine show(arg)
type(t), intent(in) :: arg
print *, allocated(arg%a), size(arg%a)
end subroutine show
end program main
