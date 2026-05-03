program xdim
implicit none

real :: x, y

print *, "dim(x,y) returns max(x - y, 0)."
print *

x = 5.0; y = 3.0
print *, "x =", x, " y =", y, " dim(x,y) =", dim(x,y)

x = 3.0; y = 5.0
print *, "x =", x, " y =", y, " dim(x,y) =", dim(x,y)

x = -2.0; y = -5.0
print *, "x =", x, " y =", y, " dim(x,y) =", dim(x,y)

x = -5.0; y = -2.0
print *, "x =", x, " y =", y, " dim(x,y) =", dim(x,y)

end program xdim
