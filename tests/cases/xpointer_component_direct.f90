program main
implicit none
type :: holder
   integer, pointer :: p(:)
end type holder
type(holder) :: h
integer, target :: a(3)
a = [10, 20, 30]
h%p => a
print *, associated(h%p), size(h%p), h%p
h%p(2) = 200
print *, a
end program main
