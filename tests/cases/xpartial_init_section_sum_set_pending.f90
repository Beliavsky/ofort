program partial_initialization_section
implicit none
real :: a(4)
a(2:3) = [7.0, 9.0]
print *, sum(a(2:3))
end program partial_initialization_section
