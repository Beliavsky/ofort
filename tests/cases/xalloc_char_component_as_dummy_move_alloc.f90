program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
call move_text(x%s)
print *, allocated(x%s), len(x%s), x%s
contains
subroutine move_text(s)
character(:), allocatable, intent(inout) :: s
character(:), allocatable :: tmp
allocate(character(len=6) :: tmp)
tmp = "abcdef"
call move_alloc(tmp, s)
end subroutine move_text
end program main
