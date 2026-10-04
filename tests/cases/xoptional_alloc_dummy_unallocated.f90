program main
implicit none
integer, allocatable :: a(:)
call show(a)
contains
subroutine show(a)
integer, allocatable, optional, intent(inout) :: a(:)
print *, present(a), allocated(a)
end subroutine show
end program main
