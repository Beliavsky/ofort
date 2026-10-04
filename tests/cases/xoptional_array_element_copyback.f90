module xoptional_array_element_copyback_mod
contains
pure elemental function optval(x, default) result(y)
real, intent(in), optional :: x
real, intent(in) :: default
real :: y
if (present(x)) then
  y = x
else
  y = default
end if
end function

subroutine set_scalar(tf, prob)
logical, intent(out) :: tf
real, intent(in), optional :: prob
real :: x
x = 0.4
tf = x < optval(prob, 0.5)
end subroutine

subroutine set_vec(tf, prob)
logical, intent(out) :: tf(:)
real, intent(in), optional :: prob
integer :: i
do i = 1, size(tf)
  call set_scalar(tf(i), prob)
end do
end subroutine
end module

program xoptional_array_element_copyback
use xoptional_array_element_copyback_mod, only: set_vec
logical :: tf(3)
call set_vec(tf)
print *, tf
print *, count(tf)
call set_vec(tf, 0.3)
print *, tf
print *, count(tf)
call set_vec(tf, 0.9)
print *, tf
print *, count(tf)
end program
