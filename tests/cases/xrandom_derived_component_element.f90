module random_component_mod
implicit none
integer, parameter :: wp = kind(1.0)
type :: rec
   integer :: i
   real(kind=wp) :: r(2)
end type rec
end module random_component_mod

program main
use random_component_mod, only: rec
implicit none
type(rec) :: x(3)
call random_number(x%r(1))
print *, all(x%r(1) >= 0.0), all(x%r(1) < 1.0)
end program main
