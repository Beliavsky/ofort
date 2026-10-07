program xio_list_directed_fields_pending
use, intrinsic :: iso_fortran_env, only: real64
implicit none
integer :: a(6), ios
complex(real64) :: z(2)
character(len=64) :: text
a = -9
text = '2*10, , 30 /'
read(text, *, iostat=ios) a
print *, ios == 0, a
text = '(1.0,2.0), (3.0,-4.0)'
read(text, *, iostat=ios) z
print *, ios == 0
print *, abs(z(1) - cmplx(1.0_real64,2.0_real64,kind=real64)) < 1.0e-12_real64
print *, abs(z(2) - cmplx(3.0_real64,-4.0_real64,kind=real64)) < 1.0e-12_real64
end program xio_list_directed_fields_pending
