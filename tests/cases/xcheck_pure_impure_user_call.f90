program main
implicit none
print *, f(3)
contains
pure function f(i)
integer, intent(in) :: i
integer :: f
f = g(i)
end function f
function g(i)
integer, intent(in) :: i
integer :: g
g = 2*i
end function g
end program main
