program xdate_and_time
implicit none

integer, parameter :: nvalues = 8

character(len=8)  :: date
character(len=10) :: time
character(len=5)  :: zone
integer :: values(nvalues)

call date_and_time(date=date)
print *, "date only:"
print *, "date = ", date
print *

call date_and_time(time=time)
print *, "time only:"
print *, "time = ", time
print *

call date_and_time(zone=zone)
print *, "zone only:"
print *, "zone = ", zone
print *

call date_and_time(values=values)
print *, "values only:"
print *, "year        =", values(1)
print *, "month       =", values(2)
print *, "day         =", values(3)
print *, "utc offset  =", values(4), "minutes"
print *, "hour        =", values(5)
print *, "minute      =", values(6)
print *, "second      =", values(7)
print *, "millisecond =", values(8)
print *

call date_and_time(date=date, time=time, zone=zone, values=values)
print *, "all arguments:"
print *, "date = ", date
print *, "time = ", time
print *, "zone = ", zone
print *, "values = ", values
print *

print *, "formatted date and time:"
write (*,'(i4.4,"-",i2.2,"-",i2.2,1x,i2.2,":",i2.2,":",i2.2,".",i3.3,1x,a)') &
   values(1), values(2), values(3), values(5), values(6), values(7), values(8), zone

end program xdate_and_time
