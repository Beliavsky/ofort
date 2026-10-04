program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: stat
character(len=80) :: msg
stat = -1
msg = "unchanged"
allocate(h%a(2), stat=stat, errmsg=msg)
print *, allocated(h%a), stat, trim(msg), size(h%a)
end program main
