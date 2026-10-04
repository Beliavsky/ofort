program xprocedure_pointer_arg_type_mismatch_reject
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p

p => takes_real
print *, p(4)

contains

integer function takes_real(x)
  real, intent(in) :: x
  takes_real = int(x) + 1
end function takes_real

end program xprocedure_pointer_arg_type_mismatch_reject
