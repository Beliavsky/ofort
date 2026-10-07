program partial_random_output
implicit none
real :: a(4)
call random_number(a)
print *, all(a >= 0.0 .and. a < 1.0)
end program partial_random_output
