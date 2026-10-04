program xisnan
real :: x(4)

x = [1.0, 0.0/0.0, 2.0, -1.0/0.0]

print *, isnan(x(1)), isnan(x(2)), isnan(x(4))
print *, ieee_is_nan(x(2)), ieee_is_nan(x)
print *, count(isnan(x))
end program xisnan
