program xprocedure_pointer_arg_rank_mismatch_reject
implicit none
abstract interface
  integer function f_scalar(x)
    integer, intent(in) :: x
  end function f_scalar
end interface
procedure(f_scalar), pointer :: p

p => takes_array
print *, p(4)

contains

integer function takes_array(x)
  integer, intent(in) :: x(:)
  takes_array = sum(x)
end function takes_array

end program xprocedure_pointer_arg_rank_mismatch_reject
