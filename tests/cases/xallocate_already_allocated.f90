module date_mod
implicit none
type date
   integer :: year=0, month=0
end type date
end module date_mod

program main
use date_mod, only: date
implicit none
type(date), allocatable :: dates(:), dates1(:)
allocate (dates(3), source = date(2026, 1))
print*,allocated(dates), allocated(dates1)
allocate (dates1, mold=dates)
print "(*(1x,i4.4,'-',i2.2))", dates
print "(*(1x,i4.4,'-',i2.2))", dates1
allocate (dates(4))
end program main
