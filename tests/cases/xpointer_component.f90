! Pending pointer/allocatable regression: pointer component association.
! Expected output when fixed:
! T 4
! 123

program main
implicit none
type :: holder
   integer, pointer :: p
end type holder
integer, target :: x
type(holder) :: h
x = 4
h%p => x
print *, associated(h%p), h%p
h%p = 123
print *, x
end program main
