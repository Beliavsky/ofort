program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: source
source = 42
allocate(h%a(3), source=source)
print *, allocated(h%a), lbound(h%a), ubound(h%a), h%a
end program main
