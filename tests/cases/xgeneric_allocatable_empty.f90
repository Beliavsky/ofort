module m
implicit none
interface read_vec
   module procedure read_int_vec, read_real_vec
end interface
contains
subroutine read_int_vec(unit, x)
integer, intent(in) :: unit
integer, allocatable, intent(out) :: x(:)
allocate(x(1))
x = -1
print *, "int"
end subroutine
subroutine read_real_vec(unit, x)
integer, intent(in) :: unit
real, allocatable, intent(out) :: x(:)
allocate(x(1))
x = 1.0
print *, "real"
end subroutine
end module

program main
use m, only: read_vec
implicit none
integer :: unit
real, allocatable :: x(:)
unit = 10
call read_vec(unit, x)
print *, x
end program
