program main
implicit none
call show()
contains
subroutine show(a)
integer, allocatable, optional, intent(inout) :: a(:)
print *, present(a)
end subroutine show
end program main
