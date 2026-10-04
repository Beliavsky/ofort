module kind_field_mod
implicit none
integer, parameter :: wp = kind(1.0)
type :: rec
   real(kind=wp) :: x(2)
end type rec
end module kind_field_mod

program main
use kind_field_mod, only: rec
implicit none
type(rec) :: r
r%x = [1.0, 2.0]
print *, r%x
end program main
