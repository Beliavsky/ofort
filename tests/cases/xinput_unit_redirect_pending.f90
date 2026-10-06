program input_unit_redirect
use, intrinsic :: iso_fortran_env, only: input_unit
implicit none
integer :: u, ios, first, second

open(newunit=u, file='input_unit_redirect.txt', status='replace')
write(u, '(i0)') 17
write(u, '(i0)') 29
close(u)
open(unit=input_unit, file='input_unit_redirect.txt', status='old', action='read')
read(*, *, iostat=ios) first
if (ios /= 0) error stop 'READ(*) ignored redirected INPUT_UNIT'
read(input_unit, *, iostat=ios) second
if (ios /= 0) error stop 'READ(INPUT_UNIT) ignored redirected INPUT_UNIT'
print *, first, second
read(*, *, iostat=ios) first
if (ios >= 0) error stop 'expected end of redirected input'
close(input_unit, status='delete')
end program input_unit_redirect
! Expected normalized stdout: 17 29
! Expected exit status: 0, with no stdin required.
