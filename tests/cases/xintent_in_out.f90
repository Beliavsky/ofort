module m
contains
subroutine inc(x)
real, intent(in out) :: x
x = x + 1.0
end subroutine inc
end module m

program xintent_in_out
use m
real :: x
x = 2.0
call inc(x)
print *, x
end program xintent_in_out
