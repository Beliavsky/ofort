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
end module m
program xprocedure_pointer_component_null_assign
use m
implicit none
type(holder) :: obj
print *, associated(obj%p)
obj%p => add_ten
print *, associated(obj%p), associated(obj%p, add_ten), obj%p(5)
obj%p => null()
print *, associated(obj%p), associated(obj%p, add_ten)
end program xprocedure_pointer_component_null_assign
