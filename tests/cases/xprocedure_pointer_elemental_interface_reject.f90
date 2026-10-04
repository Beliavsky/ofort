program xprocedure_pointer_elemental_mismatch_reject
implicit none
abstract interface
  elemental integer function f_elem(x)
    integer, intent(in) :: x
  end function f_elem
end interface
procedure(f_elem), pointer :: p

p => scalar_func
print *, p(4)

contains

integer function scalar_func(x)
  integer, intent(in) :: x
  scalar_func = x + 1
end function scalar_func

end program xprocedure_pointer_elemental_mismatch_reject
