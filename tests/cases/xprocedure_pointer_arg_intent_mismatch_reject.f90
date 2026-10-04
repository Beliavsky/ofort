program xprocedure_pointer_arg_intent_mismatch_reject
implicit none
abstract interface
  integer function f_int_in(x)
    integer, intent(in) :: x
  end function f_int_in
end interface
procedure(f_int_in), pointer :: p

p => takes_inout
print *, p(4)

contains

integer function takes_inout(x)
  integer, intent(inout) :: x
  x = x + 1
  takes_inout = x
end function takes_inout

end program xprocedure_pointer_arg_intent_mismatch_reject
