program xprocedure_dummy_nonpointer_assign_reject
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
call apply(add_ten)
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
  f => double_it
end subroutine apply
end program xprocedure_dummy_nonpointer_assign_reject
