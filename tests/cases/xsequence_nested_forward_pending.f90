program xsequence_nested_forward_pending
implicit none
integer :: a(4,4), i
a = reshape([(i, i=1,16)], [4,4])
call outer(a(2,2))
print *, a
a = reshape([(i, i=1,16)], [4,4])
call outer_explicit(a(3,1))
print *, a
contains
subroutine outer(x)
integer, intent(inout) :: x(*)
call inner_matrix(x(3), 2)
end subroutine outer
subroutine inner_matrix(x, lda)
integer, intent(in) :: lda
integer, intent(inout) :: x(lda,*)
x(1:2,1) = [100, 200]
x(1:2,2) = [300, 400]
end subroutine inner_matrix
subroutine outer_explicit(x)
integer, intent(inout) :: x(2,3)
call inner_vector(x(2,2))
end subroutine outer_explicit
subroutine inner_vector(x)
integer, intent(inout) :: x(*)
x(1:2) = [700, 800]
end subroutine inner_vector
end program xsequence_nested_forward_pending
