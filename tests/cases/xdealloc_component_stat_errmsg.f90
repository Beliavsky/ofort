program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: stat
character(len=80) :: msg
allocate(h%a(2))
h%a = [3, 4]
stat = -1
msg = "unchanged"
deallocate(h%a, stat=stat, errmsg=msg)
print *, allocated(h%a), stat, trim(msg)
end program main
