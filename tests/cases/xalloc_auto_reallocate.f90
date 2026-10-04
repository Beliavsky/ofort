! Pending pointer/allocatable regression: intrinsic assignment reallocates allocatable arrays.
! Expected output when fixed:
! 3 1 2 3
! 5 10 20 30 40 50

program main
implicit none
integer, allocatable :: a(:)
a = [1, 2, 3]
print *, size(a), a
a = [10, 20, 30, 40, 50]
print *, size(a), a
end program main
