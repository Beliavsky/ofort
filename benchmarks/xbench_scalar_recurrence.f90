integer, parameter :: n = 250000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y
integer :: i
x = 0.125_dp
y = 1.0_dp
do i = 1, n
   y = 0.999999_dp*y + x
end do
print*, n, y
end
