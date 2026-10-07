program xnoncontig_explicit_pending
implicit none
integer :: a(8)
a = [1, 2, 3, 4, 5, 6, 7, 8]
call update(a(2:8:2))
print *, a
call replace(a(7:1:-2))
print *, a
contains
subroutine update(x)
integer, intent(inout) :: x(0:3)
integer :: i
do i = 0, 3
   x(i) = x(i) + 10*(i+1)
end do
end subroutine update
subroutine replace(x)
integer, intent(out) :: x(-2:1)
x = [100, 200, 300, 400]
end subroutine replace
end program xnoncontig_explicit_pending
