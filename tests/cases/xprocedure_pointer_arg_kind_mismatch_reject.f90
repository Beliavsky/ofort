program xprocedure_pointer_arg_kind_mismatch_reject
implicit none
abstract interface
  integer function f_i4(x)
    integer, intent(in) :: x
  end function f_i4
end interface
procedure(f_i4), pointer :: p

p => takes_i8
print *, p(4)

contains

integer function takes_i8(x)
  integer(kind=8), intent(in) :: x
  takes_i8 = int(x) + 1
end function takes_i8

end program xprocedure_pointer_arg_kind_mismatch_reject
