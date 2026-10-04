program xprocedure_pointer_value_reject
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
contains
subroutine s(f)
  procedure(f_int), pointer, value :: f
end subroutine s
end program xprocedure_pointer_value_reject
