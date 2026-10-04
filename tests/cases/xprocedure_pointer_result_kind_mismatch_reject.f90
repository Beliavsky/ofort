program xprocedure_pointer_result_kind_mismatch_reject
implicit none
abstract interface
  integer(kind=8) function f_i8(x)
    integer, intent(in) :: x
  end function f_i8
end interface
procedure(f_i8), pointer :: p

p => returns_i4
print *, p(4)

contains

integer function returns_i4(x)
  integer, intent(in) :: x
  returns_i4 = x + 1
end function returns_i4

end program xprocedure_pointer_result_kind_mismatch_reject
