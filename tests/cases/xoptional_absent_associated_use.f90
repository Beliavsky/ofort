program main
implicit none
call show()
contains
subroutine show(p)
integer, pointer, optional, intent(inout) :: p(:)
print *, associated(p)
end subroutine show
end program main
