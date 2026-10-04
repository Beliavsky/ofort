program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
h%a = [1, 2, 3]
h%a = [10, 20, 30, 40]
print *, allocated(h%a), size(h%a), h%a
end program main
