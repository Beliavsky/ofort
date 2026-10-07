program xio_internal_records_pending
implicit none
character(len=24) :: records(3)
integer :: values(6), i, ios
write(records, '(2(i3))', iostat=ios) (i, i=1,6)
print *, ios == 0
print *, records(1) == '  1  2', records(2) == '  3  4', records(3) == '  5  6'
values = -1
read(records, '(2(i3))', iostat=ios) values
print *, ios == 0, values
end program xio_internal_records_pending
