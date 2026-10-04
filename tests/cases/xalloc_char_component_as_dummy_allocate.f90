program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
call set_text(x%s)
print *, allocated(x%s), len(x%s), x%s
contains
subroutine set_text(s)
character(:), allocatable, intent(inout) :: s
allocate(character(len=5) :: s)
s = "hello"
end subroutine set_text
end program main
