module m
implicit none
integer, parameter :: dp = kind(1.0d0)
interface stats
   module procedure stat_vec_str_many
end interface
contains
function stat_vec_str_many(str_stat, xx) result(xstat)
character(len=*), intent(in) :: str_stat(:)
real(kind=dp), intent(in) :: xx(:)
real(kind=dp), allocatable :: xstat(:)
allocate(xstat(size(str_stat)))
xstat = sum(xx)
end function stat_vec_str_many
end module m

program main
use m
implicit none
real(kind=dp), target :: xx(3,2)
real(kind=dp), pointer :: xuse(:)
character(len=4) :: cstats(2) = ["mean", "sd  "]
xx = reshape([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp, 5.0_dp, 6.0_dp], shape(xx))
xuse => xx(:,2)
print *, stats(cstats, xuse)
end program main
