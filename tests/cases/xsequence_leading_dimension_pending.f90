program xsequence_leading_dimension_pending
implicit none
integer :: a(4,4), i
a = reshape([(i, i=1,16)], [4,4])
call update(a(2,2), 2, 2, 3)
print *, a
a = reshape([(i, i=1,16)], [4,4])
call update(a(2,2), 4, 2, 2)
print *, a
contains
subroutine update(x, lda, rows, cols)
integer, intent(in) :: lda, rows, cols
integer, intent(inout) :: x(lda,*)
integer :: row, col
do col = 1, cols
   do row = 1, rows
      x(row,col) = x(row,col) + 100*col + 10*row
   end do
end do
end subroutine update
end program xsequence_leading_dimension_pending
