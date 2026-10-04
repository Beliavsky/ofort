! Pending regression: generic resolution by dummy argument rank.
! Expected output when fixed:
! scalar 5
! vector 3 60

module m_generic_rank
implicit none
interface report
   module procedure report_scalar
   module procedure report_vector
end interface
contains
subroutine report_scalar(x)
   integer, intent(in) :: x
   print *, "scalar", x
end subroutine report_scalar

subroutine report_vector(x)
   integer, intent(in) :: x(:)
   print *, "vector", size(x), sum(x)
end subroutine report_vector
end module m_generic_rank

program main
use m_generic_rank, only: report
implicit none
call report(5)
call report([10, 20, 30])
end program main
