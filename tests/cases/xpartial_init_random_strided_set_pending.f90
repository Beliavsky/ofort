program partial_random_output
implicit none
real :: a(4)
call random_number(a(1:4:2))
print *, all(a(1:4:2) >= 0.0 .and. a(1:4:2) < 1.0)
end program partial_random_output
