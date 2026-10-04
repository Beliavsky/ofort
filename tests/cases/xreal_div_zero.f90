program xreal_div_zero
real :: x(4), y(3)

x = [1.0/0.0, 0.0/0.0, -1.0/0.0, 1.0]
y = [2.0, 0.0, -2.0] / 0.0

print *, x(1) > huge(x(1)), x(2) /= x(2), x(3) < -huge(x(3))
print *, y(1) > huge(y(1)), y(2) /= y(2), y(3) < -huge(y(3))
end program xreal_div_zero
