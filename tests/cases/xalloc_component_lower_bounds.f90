program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: stat
character(len=100) :: msg
msg = ""
allocate(h%a(-1:1), stat=stat, errmsg=msg)
h%a = [10, 20, 30]
print *, stat, trim(msg), lbound(h%a), ubound(h%a), h%a(-1), h%a(1)
end program main
