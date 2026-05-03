implicit none
character (len=*), parameter :: xfile = "temp.txt"
integer, parameter :: iu = 20
real :: i(3)
real, allocatable :: ichk(:)
integer :: isize
character (len=100) :: text
i = [10.1, 20.1, 30.1]
open (unit=iu, file=xfile, action="write", status="replace")
write (iu,*) size(i), i
close(unit=iu)
open (unit=iu, file=xfile, action="read", status="old", position="rewind")
read (iu,"(a)") text
read (text,*) isize
allocate (ichk(isize))
read (text,*) isize, ichk
print*,"ichk = ", ichk
print*,"sum(abs(i-ichk)) = ", sum(abs(i-ichk))
end
