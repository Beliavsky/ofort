program partial_random_output
implicit none
real :: a(4)
call random_number(a(2))
print *, a(2) >= 0.0 .and. a(2) < 1.0
end program partial_random_output
