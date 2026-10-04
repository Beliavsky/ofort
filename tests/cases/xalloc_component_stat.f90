program main
implicit none
type :: holder
   integer, allocatable :: a(:)
end type holder
type(holder) :: h
integer :: stat
character(len=100) :: msg
msg = ""
allocate(h%a(3), stat=stat, errmsg=msg)
h%a = [1, 2, 3]
print *, stat, trim(msg), allocated(h%a), size(h%a), h%a
deallocate(h%a, stat=stat, errmsg=msg)
print *, stat, trim(msg), allocated(h%a)
deallocate(h%a, stat=stat, errmsg=msg)
print *, stat, trim(msg), allocated(h%a)
end program main
