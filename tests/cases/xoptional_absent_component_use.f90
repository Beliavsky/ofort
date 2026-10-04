program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
call show()
contains
subroutine show(arg)
type(t), optional, intent(in) :: arg
print *, allocated(arg%a)
end subroutine show
end program main
