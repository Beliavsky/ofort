program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
allocate(character(len=7) :: x%s)
x%s = "testing"
call show(x)
contains
subroutine show(arg)
type(t), intent(in) :: arg
print *, allocated(arg%s), len(arg%s), arg%s
end subroutine show
end program main
