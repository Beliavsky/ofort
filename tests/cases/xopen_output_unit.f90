program xopen_output_unit
use iso_fortran_env, only: output_unit
implicit none
integer :: ios

open(output_unit, encoding="utf-8", iostat=ios)
write(output_unit, *) "hello", ios

end program xopen_output_unit
