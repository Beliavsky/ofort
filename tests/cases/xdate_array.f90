module date_mod
implicit none
type date
   integer :: year, month
end type date
end module date_mod

program main
use date_mod, only: date
implicit none
integer, parameter :: n = 4
type(date) :: dates(n)
integer :: i
dates%year  = 2026
dates%month = [(i, i=8,11)]
print "(*(1x,i4.4,'-',i2.2))", dates
end program main
