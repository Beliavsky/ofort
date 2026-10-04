program main
implicit none
integer, allocatable :: a(:)
a = [1, 2, 3]
a = [10, 20, 30, 40]
print *, allocated(a), size(a), a
end program main
