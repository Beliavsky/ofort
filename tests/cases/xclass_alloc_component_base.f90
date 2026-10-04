program main
implicit none
type :: base
   integer :: i
end type base
type :: holder
   class(base), allocatable :: x
end type holder
type(holder) :: h
allocate(base :: h%x)
h%x%i = 7
print *, allocated(h%x), h%x%i
end program main
