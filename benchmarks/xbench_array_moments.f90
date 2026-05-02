integer, parameter :: n = 1000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, sum(x)/n, sum(x**2)/n
end
