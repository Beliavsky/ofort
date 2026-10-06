program partial_initialization_assignment
implicit none
real :: a(3)
a(2:3) = 7.0
print *, a(2), a(3)
end program partial_initialization_assignment
