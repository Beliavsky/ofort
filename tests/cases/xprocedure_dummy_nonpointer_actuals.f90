program xprocedure_dummy_nonpointer_actuals
implicit none
type :: holder
  procedure(f_int), pointer, nopass :: p => null()
end type holder
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
type(holder) :: obj
obj%p => double_it
call apply(add_ten)
call apply(obj%p)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
integer function double_it(x)
  integer, intent(in) :: x
  double_it = 2*x
end function double_it
subroutine apply(f)
  procedure(f_int) :: f
  print *, f(5)
end subroutine apply
end program xprocedure_dummy_nonpointer_actuals
