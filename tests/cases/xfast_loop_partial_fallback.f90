program xfast_loop_partial_fallback
implicit none
real :: h, s
integer :: i
h = 1.0
s = 0.0
do i = 1, 3
   h = max(h, 0.0)
   s = s + h
   h = next_h(h)
end do
print *, h, s
contains
real function next_h(x)
real, intent(in) :: x
next_h = x + 1.0
end function next_h
end program xfast_loop_partial_fallback
