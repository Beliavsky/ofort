program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
allocate(character(len=4) :: x%s)
x%s = "gone"
call clear_text(x%s)
print *, allocated(x%s)
contains
subroutine clear_text(s)
character(:), allocatable, intent(inout) :: s
deallocate(s)
end subroutine clear_text
end program main
