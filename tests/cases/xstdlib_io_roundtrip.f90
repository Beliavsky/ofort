program main
use stdlib_io, only: savetxt, loadtxt
implicit none
integer, parameter :: dp = kind(1.0d0)
integer, parameter :: nrow = 10**3, ncol = 3
real(kind=dp) :: x(nrow, ncol)
real(kind=dp), allocatable :: y(:,:)
integer :: i, j

do j = 1, ncol
   do i = 1, nrow
      x(i,j) = real(10*j + i, kind=dp) / 7.0_dp
   end do
end do

print*,"calling savetxt"
call savetxt("xstdlib_io_roundtrip.txt", x, delimiter=",", header="a,b,c", comments="")
print*,"calling loadtxt"
call loadtxt("xstdlib_io_roundtrip.txt", y, skiprows=1, delimiter=",")

print *, shape(y)
print *, maxval(abs(x - y)) < 1.0d-12

end program main
