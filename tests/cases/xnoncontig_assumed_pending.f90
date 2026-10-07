program xnoncontig_assumed_pending
implicit none
integer :: a(4,4), i
a = reshape([(i, i=1,16)], [4,4])
call update(a(4:2:-2,1:3:2))
print *, a
contains
subroutine update(x)
integer, intent(inout) :: x(0:,-2:)
integer :: row, col
print *, lbound(x), ubound(x), shape(x)
do col = lbound(x,2), ubound(x,2)
   do row = lbound(x,1), ubound(x,1)
      x(row,col) = x(row,col) + 100*(row+1) + 10*(col+3)
   end do
end do
end subroutine update
end program xnoncontig_assumed_pending
