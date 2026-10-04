module xvector_subscript_actual_mod
implicit none
contains

subroutine disp_vec(v)
integer, intent(in) :: v(:)
print *, v
end subroutine disp_vec

subroutine disp_mat(a)
integer, intent(in) :: a(:, :)
integer :: i
do i = 1, size(a, 1)
   print *, a(i, :)
end do
end subroutine disp_mat

end module xvector_subscript_actual_mod

program xvector_subscript_actual
use xvector_subscript_actual_mod, only: disp_vec, disp_mat
implicit none
integer :: v(4), a(3, 4), i, j

v = [11, 12, 13, 14]
forall (i = 1:3, j = 1:4) a(i, j) = 10*i + j

call disp_vec(v([1, 3]))
call disp_mat(a([1, 3], :))
call disp_mat(a([1, 3], [2, 4]))

end program xvector_subscript_actual
