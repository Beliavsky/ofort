program main
use, intrinsic :: iso_fortran_env, only: output_unit
implicit none
integer :: n, rate
integer :: x(3)
x = [1, 2, 3]
call random_seed(size=n)
call system_clock(count_rate=rate)
write(unit=output_unit, fmt=*) n, rate
print *, size(array=x, dim=1)
print *, sum(x, dim=1)
end program main
