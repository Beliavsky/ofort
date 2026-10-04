program xprocedure_pointer_component_dummy_assign
implicit none
abstract interface
  integer function f_int(i)
    integer, intent(in) :: i
  end function f_int
end interface
type :: holder
  procedure(f_int), pointer, nopass :: p => null()
end type holder
type(holder) :: obj
call set_proc(obj%p)
print *, associated(obj%p), obj%p(6)
obj%p => null()
print *, associated(obj%p)
contains
subroutine set_proc(f)
  procedure(f_int), pointer :: f
  f => twice
end subroutine set_proc
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_component_dummy_assign
