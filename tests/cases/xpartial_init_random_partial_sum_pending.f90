program partial_random_output
implicit none
real :: a(4)
call random_number(a(2:3))
print *, sum(a)
end program partial_random_output
