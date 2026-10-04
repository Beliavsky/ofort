program xopen_status_new_iostat
implicit none
integer :: iu, ierr
open(newunit=iu, file="xopen_status_new_iostat.tmp", status="replace", action="write")
write(iu,*) 1
close(iu)
open(newunit=iu, file="xopen_status_new_iostat.tmp", status="new", action="write", iostat=ierr)
print *, ierr /= 0
open(newunit=iu, file="xopen_status_new_iostat.tmp", status="old", action="read", iostat=ierr)
print *, ierr == 0
close(iu, status="delete")
end program xopen_status_new_iostat
