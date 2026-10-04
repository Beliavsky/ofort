program test_ieee_arithmetic
use, intrinsic :: ieee_arithmetic
implicit none
integer, parameter :: wp = kind(1.0)
real(kind=wp) :: z, vec(6), nan_value, t
z = 0.0_wp
t = tiny(z)
vec = [z/z, z/1.0_wp, -z/1.0_wp, 1.0_wp/z, -1.0_wp/z, t/10]
print *, ieee_value(0.0, ieee_positive_inf), 1.0/z
nan_value = ieee_value(0.0, ieee_quiet_nan)
print *, "NaN == NaN?", nan_value == nan_value
print "(a,*(1x,l1))", "ieee_is_nan", ieee_is_nan(vec)
print "(a,*(1x,l1))", "ieee_is_negative", ieee_is_negative(vec)
print "(a,*(1x,l1))", "ieee_is_finite", ieee_is_finite(vec)
print "(a,*(1x,l1))", "ieee_is_normal", ieee_is_normal(vec)
end program test_ieee_arithmetic
