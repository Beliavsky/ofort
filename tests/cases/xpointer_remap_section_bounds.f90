program main
implicit none
integer, target :: a(6)
integer, pointer :: p(:)
a = [10, 20, 30, 40, 50, 60]
p(-1:) => a(2:6:2)
print *, associated(p), lbound(p), ubound(p), p(-1), p(0), p(1)
p(0) = 400
print *, a
end program main
