program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: source(2)
source = [7, 8]
allocate(h%a(2), source=source)
print *, allocated(h%a), lbound(h%a), ubound(h%a), h%a
end program main
