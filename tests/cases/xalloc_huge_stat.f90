program xalloc_huge_stat
implicit none
integer :: ierr
real, allocatable :: x(:)
character(len=80) :: msg
allocate(x(10000000000_8), stat=ierr, errmsg=msg)
print *, ierr /= 0, trim(msg)
end program xalloc_huge_stat
