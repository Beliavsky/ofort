program xprocedure_pointer_optional_dummy_assign
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
procedure(f_int), pointer :: p
p => null()
call set_proc(p)
print *, associated(p), p(5)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
subroutine set_proc(q)
  procedure(f_int), pointer, optional :: q
  if (present(q)) q => add_ten
end subroutine set_proc
end program xprocedure_pointer_optional_dummy_assign
