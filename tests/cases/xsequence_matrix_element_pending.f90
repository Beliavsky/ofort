program xsequence_matrix_element_pending
implicit none
integer :: a(3,4), i
a = reshape([(i, i=1,12)], [3,4])
call update(a(2,2), 5)
print *, a
contains
subroutine update(x, n)
integer, intent(in) :: n
integer, intent(inout) :: x(*)
integer :: j
print *, x(1:n)
do j = 1, n
   x(j) = x(j) + 100*j
end do
end subroutine update
end program xsequence_matrix_element_pending
