program xspacing
implicit none

integer, parameter :: n = 7

integer :: i
real :: a(n)

a = [-10.0, -1.0, -0.5, 0.0, 0.5, 1.0, 10.0]

print *, "spacing(x) returns the absolute spacing of model numbers near x."
print *

print *, "default real examples:"
do i = 1, n
   print *, "x =", a(i), " spacing(x) =", spacing(a(i))
end do
print *

print *, "kind examples:"
print *, "spacing(1.0)   =", spacing(1.0)
print *, "spacing(1.0_4) =", spacing(1.0_4)
print *, "spacing(1.0_8) =", spacing(1.0_8)
print *

print *, "nearby-value examples:"
print *, "spacing(1.0)              =", spacing(1.0)
print *, "spacing(nearest(1.0,1.0)) =", spacing(nearest(1.0,1.0))
print *, "spacing(2.0)              =", spacing(2.0)
print *

print *, "spacing(0.0) is the spacing near zero:"
print *, "spacing(0.0) =", spacing(0.0)
print *, "tiny(0.0)    =", tiny(0.0)

end program xspacing
