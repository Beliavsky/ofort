program xmaxloc_minloc
implicit none

integer, parameter :: n = 6
integer, parameter :: nrow = 3
integer, parameter :: ncol = 4

integer :: v(n)
integer :: a(nrow,ncol)
integer :: loc1(1), loc2(2)
integer :: loc_col(ncol), loc_row(nrow)
logical :: mask2(nrow,ncol)

v = [4, 9, -2, 9, 5, -7]

a = reshape([ &
   3,  8, -1, &
   5,  2, 11, &
   7, 11,  0, &
  -4,  6, 11  &
], [nrow,ncol])

mask2 = a > 0

print *, "v = ", v
print *, "a ="
print *, a(1,:)
print *, a(2,:)
print *, a(3,:)

loc1 = maxloc(v)
print *, "maxloc(v) = ", loc1, " value = ", v(loc1(1))

loc1 = minloc(v)
print *, "minloc(v) = ", loc1, " value = ", v(loc1(1))

loc1 = maxloc(v, mask = v < 9)
print *, "maxloc(v, mask=v<9) = ", loc1, " value = ", v(loc1(1))

loc1 = minloc(v, mask = v > 0)
print *, "minloc(v, mask=v>0) = ", loc1, " value = ", v(loc1(1))

loc2 = maxloc(a)
print *, "maxloc(a) = ", loc2, " value = ", a(loc2(1), loc2(2))

loc2 = minloc(a)
print *, "minloc(a) = ", loc2, " value = ", a(loc2(1), loc2(2))

loc2 = maxloc(a, mask = a < 11)
print *, "maxloc(a, mask=a<11) = ", loc2, " value = ", a(loc2(1), loc2(2))

loc2 = minloc(a, mask = a > 0)
print *, "minloc(a, mask=a>0) = ", loc2, " value = ", a(loc2(1), loc2(2))

loc_col = maxloc(a, dim = 1)
print *, "maxloc(a, dim=1) = ", loc_col

loc_col = minloc(a, dim = 1)
print *, "minloc(a, dim=1) = ", loc_col

loc_row = maxloc(a, dim = 2)
print *, "maxloc(a, dim=2) = ", loc_row

loc_row = minloc(a, dim = 2)
print *, "minloc(a, dim=2) = ", loc_row

loc_col = maxloc(a, dim = 1, mask = mask2)
print *, "maxloc(a, dim=1, mask=a>0) = ", loc_col

loc_row = minloc(a, dim = 2, mask = mask2)
print *, "minloc(a, dim=2, mask=a>0) = ", loc_row

end program xmaxloc_minloc
