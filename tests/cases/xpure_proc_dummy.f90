module xpure_proc_dummy_funcs
implicit none
integer, parameter :: wp = kind(1.0d0)

interface
   pure function f_real_real(x) result(y)
      import wp
      real(kind=wp), intent(in) :: x
      real(kind=wp) :: y
   end function f_real_real
end interface

contains

pure function square(x) result(y)
real(kind=wp), intent(in) :: x
real(kind=wp) :: y
y = x**2
end function square

pure function cube(x) result(y)
real(kind=wp), intent(in) :: x
real(kind=wp) :: y
y = x**3
end function cube

end module xpure_proc_dummy_funcs

module xpure_proc_dummy_integral_mod
use xpure_proc_dummy_funcs, only: wp, f_real_real
implicit none

contains

pure function integral(f, a, b, n) result(y)
procedure(f_real_real) :: f
real(kind=wp), intent(in) :: a, b
integer, intent(in) :: n
real(kind=wp) :: y
integer :: i
real(kind=wp) :: x, h, fsum

h = (b - a)/(n - 1)
x = a
fsum = 0.0_wp
do i = 1, n
   if (i == 1 .or. i == n) then
      fsum = fsum + f(x)/2
   else
      fsum = fsum + f(x)
   end if
   x = x + h
end do
y = h*fsum
end function integral

end module xpure_proc_dummy_integral_mod

program xpure_proc_dummy
use xpure_proc_dummy_funcs, only: wp, square, cube
use xpure_proc_dummy_integral_mod, only: integral
implicit none

print "(*(f12.6))", integral(square, 0.0_wp, 10.0_wp, 11), &
                    integral(cube, 0.0_wp, 10.0_wp, 11)

end program xpure_proc_dummy
