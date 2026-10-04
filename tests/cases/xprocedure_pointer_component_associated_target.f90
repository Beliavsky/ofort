module m
implicit none
type :: holder
  procedure(f_int), pointer, nopass :: p => null()
end type holder
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
integer function double_it(x)
  integer, intent(in) :: x
  double_it = 2*x
end function double_it
end module m
program xprocedure_pointer_component_associated_target
use m
implicit none
type(holder) :: obj
print *, associated(obj%p, add_ten), associated(obj%p, double_it)
obj%p => add_ten
print *, associated(obj%p, add_ten), associated(obj%p, double_it), obj%p(5)
obj%p => double_it
print *, associated(obj%p, add_ten), associated(obj%p, double_it), obj%p(5)
end program xprocedure_pointer_component_associated_target
