program xprocedure_pointer_dummy
implicit none
abstract interface
  integer function f_int(i)
    integer, intent(in) :: i
  end function f_int
end interface
procedure(f_int), pointer :: p => null()
p => twice
print *, apply(p, 5)
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
end program xprocedure_pointer_dummy
