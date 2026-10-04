subroutine set_unit(iunit)
integer, intent(out) :: iunit
iunit = 17
end subroutine set_unit

program main
implicit integer (i)
call set_unit(iu)
print *, iu
end program main
