module m
implicit none
type :: holder
  integer :: scale
  procedure(apply_int), pointer, pass(self) :: p => null()
end type holder
abstract interface
  integer function apply_int(x, self)
    import :: holder
    integer, intent(in) :: x
    class(holder), intent(in) :: self
  end function apply_int
end interface
contains
integer function multiply(x, self)
  integer, intent(in) :: x
  class(holder), intent(in) :: self
  multiply = self%scale * x
end function multiply
end module m
program xprocedure_pointer_component_pass_name
use m
implicit none
type(holder) :: obj
obj%scale = 3
obj%p => multiply
print *, associated(obj%p), obj%p(5)
end program xprocedure_pointer_component_pass_name
