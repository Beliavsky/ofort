program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x(2)
call set_text(x(2)%s)
print *, allocated(x(1)%s), allocated(x(2)%s), len(x(2)%s), x(2)%s
contains
subroutine set_text(s)
character(:), allocatable, intent(inout) :: s
allocate(character(len=3) :: s)
s = "cat"
end subroutine set_text
end program main
