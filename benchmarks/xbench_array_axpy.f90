integer, parameter :: n = 50000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n), y(n)
call random_number(x)
y = 2.5_dp*x + 1.0_dp
print*, n, sum(y)/n
end
