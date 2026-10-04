program main
implicit none
type :: holder
   integer, pointer :: p(:)
end type holder
type(holder) :: h
integer, target :: a(6)
a = [10, 20, 30, 40, 50, 60]
h%p => a(2:6:2)
print *, associated(h%p), size(h%p), h%p
h%p(2) = 400
print *, a
end program main
