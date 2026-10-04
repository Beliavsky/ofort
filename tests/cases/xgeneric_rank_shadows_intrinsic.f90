module m
implicit none
interface rank
   module procedure rank_real
end interface rank
contains
function rank_real(x) result(r)
real, intent(in) :: x(:)
integer :: r(size(x))
integer :: i
do i = 1, size(x)
   r(i) = i
end do
end function rank_real

function corr(x, y) result(r)
real, intent(in) :: x(:), y(:)
real :: r, xt(size(x))
xt = x
r = sum(xt * y)
end function corr
end module m

program main
use m
implicit none
real :: x(3)
x = [1.0, 2.0, 3.0]
print *, rank(x)
print *, corr(real(rank(x)), x)
end program main
