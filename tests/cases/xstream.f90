implicit none
character (len=*), parameter :: xfile = "temp.bin"
integer, parameter :: iu = 20
real :: i(3)
real, allocatable :: ichk(:)
integer :: isize
i = [10.1, 20.1, 30.1]
open (unit=iu, file=xfile, access="stream", form="unformatted", action="write", status="replace")
write (iu) size(i), i
close(unit=iu)
open (unit=iu, file=xfile, access="stream", form="unformatted", action="read", status="old")
read (iu) isize
allocate (ichk(isize))
read (iu) ichk
print*,"ichk = ", ichk
print*,"sum(abs(i-ichk)) = ", sum(abs(i-ichk))
end
