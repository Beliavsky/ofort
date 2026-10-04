program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
allocate(x%a(2))
x%a = [1, 2]
call show(x%a)
contains
subroutine show(a)
integer, allocatable, optional, intent(inout) :: a(:)
if (present(a)) print *, present(a), allocated(a), size(a), a
end subroutine show
end program main
