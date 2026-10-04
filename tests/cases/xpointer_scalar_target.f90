! Pending pointer/allocatable regression: scalar pointer association.
! Expected output when fixed:
! T 42
! 99

program main
implicit none
integer, target :: x
integer, pointer :: p
x = 42
p => x
print *, associated(p), p
p = 99
print *, x
end program main
