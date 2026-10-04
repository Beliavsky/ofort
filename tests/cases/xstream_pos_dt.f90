module stream_pos_dt_mod
implicit none
type :: rec
   integer :: i
   real :: r(2)
end type rec
end module stream_pos_dt_mod

program main
use stream_pos_dt_mod, only: rec
implicit none
integer, parameter :: iu = 10
type(rec) :: x(3), y
integer :: i
do i = 1, 3
   x(i)%i = 10*i
   x(i)%r = [real(i) + 0.25, real(i) + 0.5]
end do
open(unit=iu, file="xstream_pos_dt.tmp", action="readwrite", access="stream", form="unformatted", status="replace")
write(iu) x
read(iu, pos=13) y
print *, storage_size(x), y%i, y%r
end program main
