module m
implicit none
type :: vec
   real, allocatable :: x(:)
end type vec
contains
function make_values(n) result(x)
integer, intent(in) :: n
real :: x(n)
integer :: i
x = [(real(i), i = 1, n)]
end function make_values

elemental function moment(v, m) result(xmom)
type(vec), intent(in) :: v
integer, intent(in) :: m
real :: xmom
real :: xmean
integer :: n
n = max(1, size(v%x))
xmean = sum(v%x) / n
xmom = sum((v%x - xmean)**m) / n
end function moment
end module m

program main
use m, only: moment, vec, make_values
implicit none
integer :: i
type(vec) :: v
v = vec(x = make_values(4))
print *, size(v%x), allocated(v%x)
print *, moment(v, [(i, i = 1, 3)])
end program main
