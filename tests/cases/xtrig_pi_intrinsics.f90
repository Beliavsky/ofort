program xtrig_pi_intrinsics
implicit none
real :: x(3), y(3)

x = [0.0, 0.5, 1.0]
y = sinpi(x)
print "(*(f6.3,1x))", sinpi(0.5), cospi(1.0), tanpi(0.25)
print "(*(f6.3,1x))", asinpi(1.0), acospi(-1.0), atanpi(1.0), atan2pi(1.0, -1.0)
print "(*(f6.3,1x))", y
end program xtrig_pi_intrinsics
