program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x, y
allocate(character(len=4) :: x%s)
x%s = "wxyz"
call move_alloc(x%s, y%s)
print *, allocated(x%s), allocated(y%s), len(y%s), y%s
end program main
