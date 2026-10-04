program xwrite_char_iostat
use iso_fortran_env, only: iostat_eor
implicit none
character(len=3) :: s
integer :: ios

write(s, "(a)") "abc"
print "(a)", s
write(s, "(a)", iostat=ios) "abcd"
print *, ios, ios == iostat_eor, s

end program xwrite_char_iostat
