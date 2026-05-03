real function twice(x)
real, intent(in) :: x
twice = 2.0*x
end function twice
double precision function prho()
prho = 7.5d0
end function prho
program main
implicit none
print *, twice(3.0)
print *, prho()
end program main
