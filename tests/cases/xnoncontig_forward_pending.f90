program xnoncontig_forward_pending
implicit none
integer :: a(10)
a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
call outer(a(2:10:2))
print *, a
print *, change(a(9:1:-2))
print *, a
contains
subroutine outer(x)
integer, intent(inout) :: x(:)
call inner(x(2:4:2))
end subroutine outer
subroutine inner(x)
integer, intent(inout) :: x(2)
x = x + [100, 200]
end subroutine inner
integer function change(x) result(total)
integer, intent(inout) :: x(:)
x = 10*x
total = sum(x)
end function change
end program xnoncontig_forward_pending
