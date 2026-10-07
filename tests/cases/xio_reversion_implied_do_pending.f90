program xio_reversion_implied_do_pending
implicit none
integer :: u, ios, i, values(9), row(3)
open(newunit=u, file='audit_reversion.txt', status='replace', action='readwrite')
write(u, '(3(i3))') (i*i, i=1,9)
rewind(u)
do i = 1, 3
   read(u, '(3(i3))', iostat=ios) row
   print *, ios == 0, row
end do
rewind(u)
values = -1
read(u, '(3(i3))', iostat=ios) (values(i), i=1,9)
print *, ios == 0, values
close(u, status='delete')
end program xio_reversion_implied_do_pending
