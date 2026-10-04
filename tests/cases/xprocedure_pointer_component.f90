program xprocedure_pointer_component
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
obj%p => twice
print *, associated(obj%p), obj%p(6)
obj%p => null()
print *, associated(obj%p)
contains
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_component
