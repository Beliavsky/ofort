program main
implicit none
integer, target :: x
integer, pointer :: p
x = 5
p => x
associate (a => p)
   a = 50
end associate
print *, x, p
end program main
