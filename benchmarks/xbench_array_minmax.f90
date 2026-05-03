integer, parameter :: n = 50000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x(n)
call random_number(x)
print*, n, minval(x), maxval(x)
end
