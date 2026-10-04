program main
implicit none
integer, allocatable :: a(:)
a = [1, 2, 3]
print *, allocated(a), size(a), a
end program main
