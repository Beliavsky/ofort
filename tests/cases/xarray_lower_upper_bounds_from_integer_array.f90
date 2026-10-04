program xarray_lower_upper_bounds_from_integer_array
implicit none
integer, parameter :: lb(2) = [0, -1]
integer, parameter :: ub(2) = [2, 1]
integer :: a(lb:ub)
integer :: b(0:ub)
print *, rank(a), lbound(a), ubound(a), shape(a)
print *, rank(b), lbound(b), ubound(b), shape(b)
end program xarray_lower_upper_bounds_from_integer_array
