implicit none
integer :: x(3)
integer :: y(2)

open(unit=11, file="xrewind.tmp", status="replace")
write(11,*) 10, 20, 30
write(11,*) 40, 50

rewind 11
read(11,*) x
print *, x

rewind(unit=11)
read(11,*) y
print *, y
close(11)
