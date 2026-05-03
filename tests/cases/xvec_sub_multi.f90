program main
implicit none
integer :: a(-2:2,3:7)
integer :: i, j
forall (i=-2:2, j=3:7) a(i,j) = 100*i + j
print *, a([2,-1,1],[7,3,6])
end program main
