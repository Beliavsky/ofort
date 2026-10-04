program main
implicit none
integer, target :: a(6)
integer, pointer :: p(:)
a = [10, 20, 30, 40, 50, 60]
p => a(2:6:2)
print *, p
a(4) = 400
print *, p
end program main
