program main
implicit none
integer, target :: v(3)
v = [1, 2, 3]
associate (a => v(2))
   a = 20
end associate
print *, v
end program main
