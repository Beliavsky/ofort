program xprocedure_pointer_pure_reverse_mismatch_reject
implicit none
abstract interface
  integer function f_impure(x)
    integer, intent(in) :: x
  end function f_impure
end interface
procedure(f_impure), pointer :: p

p => pure_func
print *, p(4)

contains

pure integer function pure_func(x)
  integer, intent(in) :: x
  pure_func = x + 1
end function pure_func

end program xprocedure_pointer_pure_reverse_mismatch_reject
