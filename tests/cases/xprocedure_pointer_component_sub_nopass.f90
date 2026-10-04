module m
implicit none
type :: holder
  procedure(apply_sub), pointer, nopass :: p => null()
end type holder
abstract interface
  subroutine apply_sub(x, y)
    integer, intent(in) :: x
    integer, intent(out) :: y
  end subroutine apply_sub
end interface
contains
subroutine add_ten(x, y)
  integer, intent(in) :: x
  integer, intent(out) :: y
  y = x + 10
end subroutine add_ten
end module m
program xprocedure_pointer_component_sub_nopass
use m
implicit none
type(holder) :: obj
integer :: y = 0
obj%p => add_ten
call obj%p(5, y)
print *, associated(obj%p), y
end program xprocedure_pointer_component_sub_nopass
