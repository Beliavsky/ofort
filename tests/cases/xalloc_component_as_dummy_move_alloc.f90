program main
implicit none
type :: t
   integer, allocatable :: a(:)
end type t
type(t) :: x
call make_with_move(x%a)
print *, allocated(x%a), size(x%a), x%a
contains
subroutine make_with_move(a)
integer, allocatable, intent(inout) :: a(:)
integer, allocatable :: tmp(:)
allocate(tmp(3))
tmp = [4, 5, 6]
call move_alloc(tmp, a)
end subroutine make_with_move
end program main
