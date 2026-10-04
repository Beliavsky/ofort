! Pending pointer/allocatable regression: deferred-length allocatable character assignment.
! Expected output when fixed:
! 3 abc
! 6 abcdef

program main
implicit none
character(len=:), allocatable :: s
s = "abc"
print *, len(s), s
s = "abcdef"
print *, len(s), s
end program main
