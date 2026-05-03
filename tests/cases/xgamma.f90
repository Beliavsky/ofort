implicit none
integer, parameter :: dp = kind(1.0d0)
real :: x(2)
x = [4.0, 5.0]
print *, gamma(4.0_dp)
print *, log_gamma(4.0_dp)
print *, gamma(x)
print *, log_gamma(x)
end
