integer, parameter :: n = 50000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x
integer :: i
x = 1.0_dp
do i = 1, n
   call update(x)
end do
print*, n, x
contains
subroutine update(y)
  real(kind=dp), intent(inout) :: y
  y = 0.999999_dp*y + 0.125_dp
end subroutine update
end
