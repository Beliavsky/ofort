program xprocedure_pointer_function_result
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p
p => choose(.true.)
print *, associated(p), p(5)
p => choose(.false.)
print *, associated(p), p(5)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
integer function double_it(x)
  integer, intent(in) :: x
  double_it = 2*x
end function double_it
function choose(flag) result(pout)
  logical, intent(in) :: flag
  procedure(f_int), pointer :: pout
  if (flag) then
    pout => add_ten
  else
    pout => double_it
  end if
end function choose
end program xprocedure_pointer_function_result
