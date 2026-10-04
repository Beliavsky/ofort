program main
implicit none
integer, target :: v(6)
v = [1, 2, 3, 4, 5, 6]
associate (a => v(2:6:2))
   a = a * 10
end associate
print *, v
end program main
