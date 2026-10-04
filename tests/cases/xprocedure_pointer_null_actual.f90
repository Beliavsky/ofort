program xprocedure_pointer_null_actual
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface

call outer()
call outer(null())

contains

subroutine outer(f)
  procedure(f_int), pointer, optional :: f
  print *, present(f)
  if (present(f)) print *, associated(f)
end subroutine outer

end program xprocedure_pointer_null_actual
