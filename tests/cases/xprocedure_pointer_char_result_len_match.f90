program xprocedure_pointer_char_result_len_match
implicit none
abstract interface
  character(len=5) function f_char(x)
    integer, intent(in) :: x
  end function f_char
end interface
procedure(f_char), pointer :: p

p => char5
print *, trim(p(4))

contains

character(len=5) function char5(x)
  integer, intent(in) :: x
  char5 = "abcde"
end function char5

end program xprocedure_pointer_char_result_len_match
