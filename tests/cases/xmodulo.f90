program xmodulo
implicit none
integer :: a, p

a = -7
p = 3
print *, "a =", a, " p =", p
print *, "mod(a,p)    =", mod(a,p)
print *, "modulo(a,p) =", modulo(a,p)

a = 7
p = -3
print *
print *, "a =", a, " p =", p
print *, "mod(a,p)    =", mod(a,p)
print *, "modulo(a,p) =", modulo(a,p)

end program xmodulo
