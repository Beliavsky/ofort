program xlist_directed_section_read
implicit none
integer :: iu, ierr, mat(2,3)
character(len=20) :: text
open(newunit=iu, file="xlist_directed_section_read.tmp", action="write", status="replace")
write(iu,*) 1, 2, 3
write(iu,*) 4, 5
write(iu,*) 6, 7, 8
close(iu)
open(newunit=iu, file="xlist_directed_section_read.tmp", action="read", status="old")
read(iu,*) mat(1,:)
read(iu,*) mat(2,:)
print *, mat(1,:)
print *, mat(2,:)
rewind(iu)
read(iu,"(a)") text
read(iu,"(a)") text
read(text,*,iostat=ierr) mat(1,:)
print *, ierr /= 0
close(iu, status="delete")
end program xlist_directed_section_read
