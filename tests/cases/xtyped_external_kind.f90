real(kind=8) function f(x)
real(kind=8), intent(in) :: x
f = 2.0d0*x
end function f

program main
implicit none
real(kind=8), external :: f
print *, int(f(3.0d0))
end program main
