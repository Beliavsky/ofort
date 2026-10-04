program main
implicit none
integer, target :: a(3)
integer, pointer :: p(:)
a = [10, 20, 30]
p(0:) => a
print *, associated(p), lbound(p), ubound(p), p(0), p(2)
p(1) = 200
print *, a
end program main
