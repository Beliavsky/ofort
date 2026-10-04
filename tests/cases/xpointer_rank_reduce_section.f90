program main
implicit none
integer, target :: a(3,2)
integer, pointer :: col(:), row(:)
a = reshape([10, 20, 30, 40, 50, 60], shape(a))
col => a(:,2)
row => a(2,:)
print *, associated(col), size(col), col
print *, associated(row), size(row), row
col = [400, 500, 600]
row = [22, 55]
print *, a
end program main
