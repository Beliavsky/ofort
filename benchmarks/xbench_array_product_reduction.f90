integer, parameter :: n = 1000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, product(1.0_dp + x/n)
end
