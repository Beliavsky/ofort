program xprocedure_pointer_arg_optional_mismatch_reject
implicit none
abstract interface
  integer function f_req(x)
    integer, intent(in) :: x
  end function f_req
end interface
procedure(f_req), pointer :: p

p => takes_optional
print *, p(4)

contains

integer function takes_optional(x)
  integer, intent(in), optional :: x
  if (present(x)) then
    takes_optional = x
  else
    takes_optional = -1
  end if
end function takes_optional

end program xprocedure_pointer_arg_optional_mismatch_reject
