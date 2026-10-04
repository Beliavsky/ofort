program main
implicit none
call show()
contains
subroutine show(a)
integer, allocatable, optional, intent(inout) :: a(:)
if (present(a)) then
   print *, allocated(a)
else
   print *, "absent"
end if
end subroutine show
end program main
