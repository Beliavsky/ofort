program xprocedure_pointer_pure_mismatch_reject
implicit none
abstract interface
  pure integer function f_pure(x)
    integer, intent(in) :: x
  end function f_pure
end interface
procedure(f_pure), pointer :: p

p => impure_func
print *, p(4)

contains

integer function impure_func(x)
  integer, intent(in) :: x
  print *, "side effect"
  impure_func = x + 1
end function impure_func

end program xprocedure_pointer_pure_mismatch_reject
