program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: source(-1:1)
source = [10, 20, 30]
allocate(h%a, source=source)
print *, allocated(h%a), lbound(h%a), ubound(h%a), h%a(-1), h%a(1)
end program main
