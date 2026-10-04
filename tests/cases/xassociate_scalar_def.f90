program main
implicit none
integer, target :: x
x = 3
associate (a => x)
   a = 10
end associate
print *, x
end program main
