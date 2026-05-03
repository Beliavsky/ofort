module m
implicit none
contains
pure subroutine s1(i,i2,i3)
integer, intent(in) :: i
integer, intent(out) :: i2, i3
i2 = 2*i
i3 = 3*i
end subroutine s1

elemental subroutine s2(i,i2,i3)
integer, intent(in) :: i
integer, intent(out) :: i2, i3
i2 = 2*i
i3 = 3*i
end subroutine s2

pure elemental subroutine s3(i,i2,i3)
integer, intent(in) :: i
integer, intent(out) :: i2, i3
i2 = 2*i
i3 = 3*i
end subroutine s3
end module m

program main
use m
implicit none
integer :: i, i2, i3
i = 5
call s1(i, i2, i3)
print*,i,i2,i3
call s2(i, i2, i3)
print*,i,i2,i3
call s3(i, i2, i3)
print*,i,i2,i3
end program main
