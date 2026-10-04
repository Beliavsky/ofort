program xarray_bounds_from_integer_array_pending
implicit none
integer, parameter :: ub(2) = [2, 3]
integer :: a(ub)
print *, rank(a), shape(a)
end program xarray_bounds_from_integer_array_pending
