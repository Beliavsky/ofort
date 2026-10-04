program xprocedure_pointer_interface_mismatch_reject
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p

p => takes_two
print *, p(4)

contains

integer function takes_two(x, y)
  integer, intent(in) :: x, y
  takes_two = x + y
end function takes_two

end program xprocedure_pointer_interface_mismatch_reject
