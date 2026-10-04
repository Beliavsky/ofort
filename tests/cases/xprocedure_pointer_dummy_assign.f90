program xprocedure_pointer_dummy_assign
implicit none
abstract interface
  integer function f_int(i)
    integer, intent(in) :: i
  end function f_int
end interface
procedure(f_int), pointer :: p => null()
call set_proc(p)
print *, associated(p), p(6)
contains
subroutine set_proc(f)
  procedure(f_int), pointer :: f
  f => twice
end subroutine set_proc
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_dummy_assign
