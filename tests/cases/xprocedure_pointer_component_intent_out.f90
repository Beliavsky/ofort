program xprocedure_pointer_component_intent_out
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
call set_proc(obj%p)
print *, associated(obj%p), obj%p(5)
call clear_proc(obj%p)
print *, associated(obj%p)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
subroutine set_proc(f)
  procedure(f_int), pointer, intent(out) :: f
  f => add_ten
end subroutine set_proc
subroutine clear_proc(f)
  procedure(f_int), pointer, intent(out) :: f
  f => null()
end subroutine clear_proc
end program xprocedure_pointer_component_intent_out
