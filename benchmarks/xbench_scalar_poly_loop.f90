integer, parameter :: n = 5000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, s
integer :: i
x = 0.25_dp
s = 0.0_dp
do i = 1, n
   x = 0.999999_dp*x + 0.000001_dp
   s = s + x*x + 2.0_dp*x + 1.0_dp
end do
print*, n, s/n
end
