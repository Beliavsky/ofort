program xallocate_bounds_from_integer_array
implicit none
integer :: lower(2), upper(2)
integer, allocatable :: a(:,:), b(:,:)

lower = [0, -1]
upper = [2, 1]

allocate(a(lower:upper))
allocate(b(0:upper))

print *, rank(a), lbound(a), ubound(a), shape(a)
print *, rank(b), lbound(b), ubound(b), shape(b)
end program xallocate_bounds_from_integer_array
