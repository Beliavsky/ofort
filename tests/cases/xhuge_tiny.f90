program xhuge_tiny
implicit none

integer, parameter :: n_int = 4
integer, parameter :: n_real = 4

integer :: i
integer :: ia(n_int)
real :: ra(n_real)

ia = [0, 1, -1, 100]
ra = [0.0, 1.0, -1.0, 100.0]

print *, "huge(x) returns the largest model number of the same type and kind as x."
print *, "tiny(x) returns the smallest positive normalized real number of the same kind as x."
print *

print *, "integer huge examples:"
do i = 1, n_int
   print *, "ia(i) =", ia(i), " huge(ia(i)) =", huge(ia(i))
end do
print *

print *, "integer kind examples:"
print *, "huge(0)   =", huge(0)
print *, "huge(0_1) =", huge(0_1)
print *, "huge(0_2) =", huge(0_2)
print *, "huge(0_4) =", huge(0_4)
print *, "huge(0_8) =", huge(0_8)
print *

print *, "real huge and tiny examples:"
do i = 1, n_real
   print *, "ra(i) =", ra(i), &
            " huge(ra(i)) =", huge(ra(i)), &
            " tiny(ra(i)) =", tiny(ra(i))
end do
print *

print *, "real kind examples:"
print *, "huge(1.0)   =", huge(1.0)
print *, "tiny(1.0)   =", tiny(1.0)
print *, "huge(1.0_4) =", huge(1.0_4)
print *, "tiny(1.0_4) =", tiny(1.0_4)
print *, "huge(1.0_8) =", huge(1.0_8)
print *, "tiny(1.0_8) =", tiny(1.0_8)

end program xhuge_tiny
