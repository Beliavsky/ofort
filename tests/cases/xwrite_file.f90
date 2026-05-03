implicit none
character (len=*), parameter :: xfile = "temp.txt"
integer, parameter :: iu = 20
integer :: i(3), ichk(3)
i = [10, 20, 30]
open (unit=iu, file=xfile, action="write", status="replace")
write (iu,*) i
close(unit=iu)
open (unit=iu, file=xfile, action="read", status="old", position="rewind")
read (iu,*) ichk
print*,"ichk = ", ichk
print*,"sum(abs(i-ichk)) = ", sum(abs(i-ichk))
end
