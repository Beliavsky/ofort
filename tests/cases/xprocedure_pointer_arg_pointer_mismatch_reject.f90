program xprocedure_pointer_arg_pointer_mismatch_reject
implicit none
abstract interface
  integer function f_plain(x)
    integer, intent(in) :: x
  end function f_plain
end interface
procedure(f_plain), pointer :: p
integer, target :: a

a = 4
p => takes_pointer
print *, p(a)

contains

integer function takes_pointer(x)
  integer, pointer, intent(in) :: x
  takes_pointer = x
end function takes_pointer

end program xprocedure_pointer_arg_pointer_mismatch_reject
