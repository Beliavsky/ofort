program xprocedure_pointer_component_dummy
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
print *, apply(obj%p, 6)
contains
integer function apply(f, x)
  procedure(f_int) :: f
  integer, intent(in) :: x
  apply = f(x)
end function apply
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_component_dummy
