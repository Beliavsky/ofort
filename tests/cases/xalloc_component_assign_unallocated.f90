program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
h%a = [1, 2, 3]
print *, allocated(h%a), size(h%a), h%a
end program main
