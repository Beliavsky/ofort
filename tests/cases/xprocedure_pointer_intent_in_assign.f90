program xprocedure_pointer_intent_in_assign
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p
p => add_ten
call set_proc(p)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
integer function double_it(x)
  integer, intent(in) :: x
  double_it = 2*x
end function double_it
subroutine set_proc(q)
  procedure(f_int), pointer, intent(in) :: q
  q => double_it
end subroutine set_proc
end program xprocedure_pointer_intent_in_assign
