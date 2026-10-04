program xadvance_no
implicit none
integer :: i, j
write (*,"('enter 2 numbers: ')",advance="no")
read (*,*) i, j
write (*,"(a,i0)") "sum is ", i + j
end program xadvance_no
