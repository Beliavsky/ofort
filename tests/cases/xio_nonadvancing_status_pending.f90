program xio_nonadvancing_status_pending
use, intrinsic :: iso_fortran_env, only: iostat_end, iostat_eor
implicit none
integer :: u, ios, transferred
character(len=4) :: chunk
open(newunit=u, file='audit_nonadvancing.txt', status='replace', action='readwrite')
write(u, '(a)') 'abcdef'
write(u, '(a)') 'XYZ'
rewind(u)
read(u, '(a)', advance='no', iostat=ios, size=transferred) chunk
print *, ios == 0, transferred, chunk == 'abcd'
read(u, '(a)', advance='no', iostat=ios, size=transferred) chunk
print *, ios == iostat_eor, transferred, chunk == 'ef  '
read(u, '(a)', advance='no', iostat=ios, size=transferred) chunk
print *, ios == iostat_eor, transferred, chunk == 'XYZ '
read(u, '(a)', advance='no', iostat=ios, size=transferred) chunk
print *, ios == iostat_end, transferred
close(u, status='delete')
end program xio_nonadvancing_status_pending
