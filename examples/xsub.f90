module m
implicit none
integer, parameter :: dp = kind(1.0d0)
contains
subroutine mean_sd(x, xmean, xsd)
real(kind=dp), intent(in) :: x(:)
real(kind=dp) :: xmean, xsd
integer :: n
n = size(x)
xmean = sum(x)/n
if (n > 1) then
   xsd = sqrt(sum((x-xmean)**2) / n)
else
   xsd = -1.0_dp
end if
end subroutine mean_sd
end module m

program main
use m
implicit none
integer, parameter :: n = 10**7
real(kind=dp) :: x(n), xmean, xsd
call random_number(x)
call mean_sd(x, xmean, xsd)
print*,n, xmean, xsd
end program main
