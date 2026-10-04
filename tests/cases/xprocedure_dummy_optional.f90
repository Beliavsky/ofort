program xprocedure_dummy_optional
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
call apply()
call apply(add_ten)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
subroutine apply(f)
  procedure(f_int), optional :: f
  if (present(f)) then
    print *, f(5)
  else
    print *, "absent"
  end if
end subroutine apply
end program xprocedure_dummy_optional
