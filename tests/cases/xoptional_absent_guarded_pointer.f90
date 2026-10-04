program main
implicit none
call show()
contains
subroutine show(p)
integer, pointer, optional, intent(inout) :: p(:)
if (present(p)) then
   print *, associated(p)
else
   print *, "absent"
end if
end subroutine show
end program main
