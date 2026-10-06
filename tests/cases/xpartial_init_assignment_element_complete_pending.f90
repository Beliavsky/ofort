program partial_initialization_assignment
implicit none
real :: a(3)
a(2) = 7.0
a(1) = 5.0
a(3) = 9.0
print *, sum(a)
end program partial_initialization_assignment
