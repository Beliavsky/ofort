program associate_bounds
implicit none
real :: m(-2:3,0:9)
associate(a => m, b => m(:,:))
   print *, lbound(a)
   print *, lbound(b)
   print *, ubound(a)
   print *, ubound(b)
   print *, size(a), size(b)
   print *, shape(a), shape(b)
end associate
end program associate_bounds
