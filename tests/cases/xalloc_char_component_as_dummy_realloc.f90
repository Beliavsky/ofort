program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
allocate(character(len=2) :: x%s)
x%s = "hi"
call reset_text(x%s)
print *, allocated(x%s), len(x%s), x%s
contains
subroutine reset_text(s)
character(:), allocatable, intent(inout) :: s
deallocate(s)
allocate(character(len=7) :: s)
s = "testing"
end subroutine reset_text
end program main
