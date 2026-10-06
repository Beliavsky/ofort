implicit none
integer, parameter :: n = 3
integer :: i
character(len=2) :: s(n)

! Each element of a character array is a record of the internal file.
write(s, "('x',i0)") (i, i=1,n)
print "(*(1x,a))", s

do i = 1, n
   write(s(i), "('x',i0)") i
end do
print "(*(1x,a))", s
end
