! Pending regression: generic resolution by real kind.
! Expected output when fixed:
! real32
! real64

module m_generic_kind
implicit none
interface which_real
   module procedure which_real32
   module procedure which_real64
end interface
contains
subroutine which_real32(x)
   real(kind=4), intent(in) :: x
   print *, "real32"
end subroutine which_real32

subroutine which_real64(x)
   real(kind=8), intent(in) :: x
   print *, "real64"
end subroutine which_real64
end module m_generic_kind

program main
use m_generic_kind, only: which_real
implicit none
call which_real(1.0)
call which_real(1.0d0)
end program main
