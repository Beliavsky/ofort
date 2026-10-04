program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: mold(-2:0)
allocate(h%a, mold=mold)
print *, allocated(h%a), lbound(h%a), ubound(h%a), size(h%a)
end program main
