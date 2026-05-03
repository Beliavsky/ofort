module m
implicit none
contains
function f(a) result(b)
integer, intent(in) :: a(:)
integer, allocatable :: b(:)
b = pack(a, a > 0)
end function f

subroutine g(a, b)
integer, intent(in) :: a(:)
integer, allocatable, intent(out) :: b(:)
integer :: nb
print*,allocated(b)
nb = count(a > 0)
allocate (b(nb))
b = pack(a, a < 0)
end subroutine g
end module m

program main
use m
implicit none
integer :: a(3) = [-3, 4, 6]
integer, allocatable :: b(:)
b = f(a)
print*,a
print*,b
call g(a,b)
print*,b
end program main
