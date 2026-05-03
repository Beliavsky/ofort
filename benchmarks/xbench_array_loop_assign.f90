integer, parameter :: n = 10000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n), y(n), a, b
integer :: i
a = 2.5_dp
b = 1.0_dp
call random_number(x)
do i = 1, n
   y(i) = a*x(i) + b
end do
print*, n, sum(y)/n
end
