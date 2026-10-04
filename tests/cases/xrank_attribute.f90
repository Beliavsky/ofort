program xrank_attribute
implicit none
real, allocatable, rank(2) :: x
real, rank(0) :: s
allocate(x(2,3))
s = 4.5
print *, rank(x), shape(x)
print *, rank(s), s
end program xrank_attribute
