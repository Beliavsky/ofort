program xiostat_env
use, intrinsic :: iso_fortran_env, only: iostat_eor, iostat_end
implicit none
print *, iostat_end, iostat_eor
print *, is_iostat_end(iostat_end), is_iostat_eor(iostat_eor)
end program xiostat_env
