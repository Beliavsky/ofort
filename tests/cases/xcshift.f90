program xcshift
implicit none

integer, parameter :: n = 5
integer, parameter :: nrow = 3
integer, parameter :: ncol = 4

integer :: a(n)
integer :: b(nrow,ncol)
integer :: r1(n)
integer :: r2(nrow,ncol)
integer :: shift_rows(ncol)
integer :: shift_cols(nrow)
integer :: i

a = [10, 20, 30, 40, 50]

b(:,1) = [11, 21, 31]
b(:,2) = [12, 22, 32]
b(:,3) = [13, 23, 33]
b(:,4) = [14, 24, 34]

print *, "a = ", a
print *

r1 = cshift(a, shift=2)
print *, "cshift(a, shift=2):"
print *, r1
print *

r1 = cshift(a, shift=-2)
print *, "cshift(a, shift=-2):"
print *, r1
print *

print *, "b:"
do i = 1, size(b,1)
   print *, b(i,:)
end do
print *

r2 = cshift(b, shift=1, dim=1)
print *, "cshift(b, shift=1, dim=1):"
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

r2 = cshift(b, shift=-1, dim=1)
print *, "cshift(b, shift=-1, dim=1):"
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

r2 = cshift(b, shift=1, dim=2)
print *, "cshift(b, shift=1, dim=2):"
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

r2 = cshift(b, shift=-1, dim=2)
print *, "cshift(b, shift=-1, dim=2):"
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

shift_rows = [0, 1, -1, 2]
r2 = cshift(b, shift=shift_rows, dim=1)
print *, "cshift(b, shift=shift_rows, dim=1):"
print *, "shift_rows = ", shift_rows
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

shift_cols = [0, 1, -1]
r2 = cshift(b, shift=shift_cols, dim=2)
print *, "cshift(b, shift=shift_cols, dim=2):"
print *, "shift_cols = ", shift_cols
do i = 1, size(r2,1)
   print *, r2(i,:)
end do

end program xcshift
