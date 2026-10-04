program main
implicit none
integer, target :: a(6)
integer, pointer :: p(:)
a = [10, 20, 30, 40, 50, 60]
p => a(2:6:2)
print *, associated(p), size(p), p
p = [200, 400, 600]
print *, a
end program main
