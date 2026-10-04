program main
implicit none
integer, target :: v(6)
integer, pointer :: p(:)
v = [1, 2, 3, 4, 5, 6]
p => v(2:6:2)
associate (a => p)
   a = a + 100
end associate
print *, v
end program main
