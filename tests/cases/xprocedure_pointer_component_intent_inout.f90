program xprocedure_pointer_component_intent_inout
implicit none
type :: holder
  procedure(f_int), pointer, nopass :: p => null()
end type holder
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
type(holder) :: obj
obj%p => add_ten
call swap_proc(obj%p)
print *, associated(obj%p), obj%p(5)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
integer function double_it(x)
  integer, intent(in) :: x
  double_it = 2*x
end function double_it
subroutine swap_proc(f)
  procedure(f_int), pointer, intent(inout) :: f
  print *, associated(f), f(5)
  f => double_it
end subroutine swap_proc
end program xprocedure_pointer_component_intent_inout
