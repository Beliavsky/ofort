module m
implicit none
type :: holder
  integer :: scale
  procedure(apply_sub), pointer, pass(self) :: p => null()
end type holder
abstract interface
  subroutine apply_sub(x, self, y)
    import :: holder
    integer, intent(in) :: x
    class(holder), intent(in) :: self
    integer, intent(out) :: y
  end subroutine apply_sub
end interface
contains
subroutine multiply(x, self, y)
  integer, intent(in) :: x
  class(holder), intent(in) :: self
  integer, intent(out) :: y
  y = self%scale * x
end subroutine multiply
end module m
program xprocedure_pointer_component_sub_pass_name
use m
implicit none
type(holder) :: obj
integer :: y = 0
obj%scale = 3
obj%p => multiply
call obj%p(5, y)
print *, associated(obj%p), y
end program xprocedure_pointer_component_sub_pass_name
