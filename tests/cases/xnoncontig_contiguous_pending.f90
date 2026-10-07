program xnoncontig_contiguous_pending
implicit none
integer :: a(8)
a = [1, 2, 3, 4, 5, 6, 7, 8]
call update(a(1:7:2))
print *, a
call replace(a(8:2:-2))
print *, a
contains
subroutine update(x)
integer, contiguous, intent(inout) :: x(:)
print *, is_contiguous(x), size(x)
x = x + 100
end subroutine update
subroutine replace(x)
integer, contiguous, intent(out) :: x(:)
print *, is_contiguous(x), size(x)
x = [10, 20, 30, 40]
end subroutine replace
end program xnoncontig_contiguous_pending
