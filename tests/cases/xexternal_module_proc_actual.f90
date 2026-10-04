module callee_mod
implicit none
contains
real(kind=8) function g(x, n)
integer, intent(in) :: n
real(kind=8), intent(in) :: x(n)
g = x(1) + n
end function g
end module callee_mod

module apply_mod
implicit none
contains
real(kind=8) function apply(x, n, f)
integer, intent(in) :: n
real(kind=8), intent(in) :: x(n)
real(kind=8), external :: f
apply = f(x, n)
end function apply
end module apply_mod

program main
use callee_mod, only: g
use apply_mod, only: apply
implicit none
real(kind=8) :: x(2)
x = [3.0d0, 4.0d0]
print *, int(apply(x, 2, g))
end program main
