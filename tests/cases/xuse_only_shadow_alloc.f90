module m_shadow_alloc
implicit none
public :: ifalse, set_alloc
integer, parameter :: ifalse = 0
interface set_alloc
   module procedure set_alloc_int_vec
end interface
contains
subroutine set_alloc_int_vec(src, dst)
integer, intent(in) :: src(:)
integer, allocatable, intent(out) :: dst(:)
allocate(dst(size(src)))
dst = src
end subroutine
end module

program main
use m_shadow_alloc, only: set_alloc
implicit none
integer, allocatable :: ifalse(:)
call set_alloc([2, 4], ifalse)
print *, ifalse
end program
