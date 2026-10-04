! Pending regression: generic resolution by dummy argument type.
! Expected output when fixed:
! integer
! real

module m_generic_type
implicit none
interface describe
   module procedure describe_i
   module procedure describe_r
end interface
contains
subroutine describe_i(x)
   integer, intent(in) :: x
   print *, "integer"
end subroutine describe_i

subroutine describe_r(x)
   real, intent(in) :: x
   print *, "real"
end subroutine describe_r
end module m_generic_type

program main
use m_generic_type, only: describe
implicit none
call describe(3)
call describe(3.5)
end program main
