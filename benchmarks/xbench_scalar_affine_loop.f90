integer, parameter :: n = 250000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y, a, b
integer :: i
x = 0.25_dp
y = 1.0_dp
a = 1.000001_dp
b = 0.125_dp
do i = 1, n
   y = a*y + b*x
end do
print*, n, y
end
