program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
call show(x%a)
contains
subroutine show(a)
integer, allocatable, optional, intent(inout) :: a(:)
print *, present(a), allocated(a)
end subroutine show
end program main
