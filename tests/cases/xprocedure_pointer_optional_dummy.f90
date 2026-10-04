program xprocedure_pointer_optional_dummy
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p
p => null()
call check()
call check(p)
p => add_ten
call check(p)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
subroutine check(q)
  procedure(f_int), pointer, optional :: q
  if (present(q)) then
    print *, associated(q)
    if (associated(q)) print *, q(5)
  else
    print *, "absent"
  end if
end subroutine check
end program xprocedure_pointer_optional_dummy
