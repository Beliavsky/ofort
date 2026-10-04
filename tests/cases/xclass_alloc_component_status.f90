program main
implicit none
type :: base
   integer :: i
end type base
type :: holder
   class(base), allocatable :: x
end type holder
type(holder) :: h
print *, allocated(h%x)
end program main
