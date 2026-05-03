integer, parameter :: n = 100000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, xsum
integer :: i
xsum = 0.0_dp
do i = 1, n
   call random_number(x)
   xsum = xsum + x
end do
print*, n, xsum/n
end
