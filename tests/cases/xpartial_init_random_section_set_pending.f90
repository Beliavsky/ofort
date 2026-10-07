program partial_random_output
implicit none
real :: a(4)
call random_number(a(2:3))
print *, all(a(2:3) >= 0.0 .and. a(2:3) < 1.0)
end program partial_random_output
