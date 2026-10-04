module m
implicit none
integer, parameter :: dp = kind(1.0d0)
interface cbind
   module procedure cbind_mat_vec
end interface cbind
contains
function cbind_mat_vec(x1, x2) result(xmat)
real(kind=dp), intent(in) :: x1(:,:), x2(:)
real(kind=dp)             :: xmat(size(x1,1), size(x1,2)+1)
xmat(:, :size(x1,2)) = x1
xmat(:, size(x1,2)+1) = x2
end function cbind_mat_vec
end module m

program main
use m
implicit none
real(kind=dp) :: x(2,2), w(2)
x = reshape([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp], shape(x))
w = [10.0_dp, 20.0_dp]
print *, kind(matmul(x,w)), int(sum(cbind(x, matmul(x,w))))
end program main
