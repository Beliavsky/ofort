program main
implicit none
integer, target :: x, y
x = 1
y = 2
associate (a => x, b => y)
   a = b + 10
   b = a + 20
end associate
print *, x, y
end program main
