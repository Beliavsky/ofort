program main
implicit none
type :: holder
   real, allocatable :: x(:)
end type holder
type(holder) :: h
integer :: stat
character(len=100) :: msg
msg = ""
allocate(h%x(2), stat=stat, errmsg=msg)
print *, stat, trim(msg), allocated(h%x), size(h%x)
allocate(h%x(4), stat=stat, errmsg=msg)
print *, stat, trim(msg), allocated(h%x), size(h%x)
end program main
