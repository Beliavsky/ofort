program partial_random_output
implicit none
real :: a(4)
call random_number(a(1:4:2))
print *, a(2)
end program partial_random_output
