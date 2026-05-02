integer, parameter :: n = 2000000
integer, parameter :: dp = kind(1.0d0)
real(kind=dp) :: x, y, dot
integer :: i
dot = 0.0_dp
do i = 1, n
   call random_number(x)
   call random_number(y)
   dot = dot + x*y
end do
print*, n, dot/n
end
