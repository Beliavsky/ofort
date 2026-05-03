implicit none
character (len=*), parameter :: xfile = "temp_read_end_keyword.txt"
integer, parameter :: iu = 21
integer :: i
open (unit=iu, file=xfile, action="write", status="replace")
write (iu,*) 42
close (unit=iu)
open (unit=iu, file=xfile, action="read", status="old", position="rewind")
read (iu,*,end=99) i
print *, i
close (unit=iu)
end
