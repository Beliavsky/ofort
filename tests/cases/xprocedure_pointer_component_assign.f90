program xprocedure_pointer_component_assign
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
procedure(f_int), pointer :: q => null()
procedure(f_int), pointer :: r => null()
obj%p => twice
q => obj%p
print *, associated(q), q(6)
r => twice
obj%p => r
print *, associated(obj%p), obj%p(7)
contains
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_component_assign
