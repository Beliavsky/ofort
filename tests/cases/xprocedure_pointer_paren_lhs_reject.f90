program xprocedure_pointer_paren_lhs_reject
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p

(p) => add_one
print *, p(4)

contains

integer function add_one(x)
  integer, intent(in) :: x
  add_one = x + 1
end function add_one

end program xprocedure_pointer_paren_lhs_reject
