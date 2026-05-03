program xspread
implicit none

integer, parameter :: n = 4
integer, parameter :: nrow = 2
integer, parameter :: ncol = 3
integer, parameter :: ncopy1 = 1
integer, parameter :: ncopy2 = 2
integer, parameter :: ncopy3 = 3
integer, parameter :: ncopy5 = 5

integer :: a(n)
integer :: b(nrow,ncol)
integer :: r1(ncopy1,n)
integer :: r2(ncopy3,n)
integer :: r3(n,ncopy2)
integer :: r4(ncopy2,nrow,ncol)
integer :: r5(nrow,ncol,ncopy2)
integer :: i, j

a = [10, 20, 30, 40]

b(:,1) = [1, 2]
b(:,2) = [3, 4]
b(:,3) = [5, 6]

print *, "a = ", a
print *

r1 = spread(a, dim=1, ncopies=ncopy1)
print *, "spread(a, dim=1, ncopies=ncopy1):"
do i = 1, size(r1,1)
   print *, r1(i,:)
end do
print *

r2 = spread(a, dim=1, ncopies=ncopy3)
print *, "spread(a, dim=1, ncopies=ncopy3):"
do i = 1, size(r2,1)
   print *, r2(i,:)
end do
print *

r3 = spread(a, dim=2, ncopies=ncopy2)
print *, "spread(a, dim=2, ncopies=ncopy2):"
do i = 1, size(r3,1)
   print *, r3(i,:)
end do
print *

print *, "b:"
do i = 1, size(b,1)
   print *, b(i,:)
end do
print *

r4 = spread(b, dim=1, ncopies=ncopy2)
print *, "spread(b, dim=1, ncopies=ncopy2):"
do j = 1, size(r4,3)
   print *, "slice (:,:,", j, ")"
   do i = 1, size(r4,1)
      print *, r4(i,:,j)
   end do
end do
print *

r5 = spread(b, dim=3, ncopies=ncopy2)
print *, "spread(b, dim=3, ncopies=ncopy2):"
do j = 1, size(r5,3)
   print *, "slice (:,:,", j, ")"
   do i = 1, size(r5,1)
      print *, r5(i,:,j)
   end do
end do
print *

print *, "scalar source:"
print *, "spread(7, dim=1, ncopies=ncopy5) = ", spread(7, dim=1, ncopies=ncopy5)

end program xspread
