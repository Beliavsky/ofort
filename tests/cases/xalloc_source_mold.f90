! Pending pointer/allocatable regression: ALLOCATE with SOURCE= and MOLD=.
! Expected output when fixed:
! 3 1 2 3
! 3 T

program main
implicit none
integer, allocatable :: a(:), b(:)
allocate(a, source=[1, 2, 3])
allocate(b, mold=a)
print *, size(a), a
print *, size(b), allocated(b)
end program main
