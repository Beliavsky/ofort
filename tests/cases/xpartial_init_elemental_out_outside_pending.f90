program partial_elemental_output
implicit none
real :: a(4)
a = 1.0
call fill_out(a(2:3), [1, 0])
print *, a(1), a(4)
contains
elemental subroutine fill_out(x, flag)
real, intent(out) :: x
integer, intent(in) :: flag
if (flag /= 0) x = 7.0
end subroutine fill_out
elemental subroutine fill_inout(x, flag)
real, intent(inout) :: x
integer, intent(in) :: flag
if (flag /= 0) x = 7.0
end subroutine fill_inout
end program partial_elemental_output
