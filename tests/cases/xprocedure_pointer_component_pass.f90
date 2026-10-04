module m
implicit none
type :: holder
  integer :: scale
  procedure(apply_int), pointer, pass :: p => null()
end type holder
abstract interface
  integer function apply_int(self, x)
    import :: holder
    class(holder), intent(in) :: self
    integer, intent(in) :: x
  end function apply_int
end interface
contains
integer function multiply(self, x)
  class(holder), intent(in) :: self
  integer, intent(in) :: x
  multiply = self%scale * x
end function multiply
end module m
program xprocedure_pointer_component_pass
use m
implicit none
type(holder) :: obj
obj%scale = 3
obj%p => multiply
print *, associated(obj%p), obj%p(5)
end program xprocedure_pointer_component_pass
