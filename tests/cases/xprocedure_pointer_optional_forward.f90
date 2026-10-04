program xprocedure_pointer_optional_forward
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p

call outer()
p => add_ten
call outer(p)
p => null()
call outer(p)

contains

integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten

subroutine outer(f)
  procedure(f_int), pointer, optional :: f
  call inner(f)
end subroutine outer

subroutine inner(g)
  procedure(f_int), pointer, optional :: g
  if (present(g)) then
    print *, associated(g)
    if (associated(g)) print *, g(5)
  else
    print *, "absent"
  end if
end subroutine inner

end program xprocedure_pointer_optional_forward
