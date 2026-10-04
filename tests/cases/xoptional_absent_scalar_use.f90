program main
implicit none
call show()
contains
subroutine show(i)
integer, optional, intent(in) :: i
print *, i
end subroutine show
end program main
