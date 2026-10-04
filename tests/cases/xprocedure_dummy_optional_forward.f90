program xprocedure_dummy_optional_forward
implicit none
abstract interface
  integer function f_int(x)
    integer, intent(in) :: x
  end function f_int
end interface
call outer()
call outer(add_ten)
contains
integer function add_ten(x)
  integer, intent(in) :: x
  add_ten = x + 10
end function add_ten
subroutine outer(f)
  procedure(f_int), optional :: f
  call inner(f)
end subroutine outer
subroutine inner(g)
  procedure(f_int), optional :: g
  if (present(g)) then
    print *, g(5)
  else
    print *, "absent"
  end if
end subroutine inner
end program xprocedure_dummy_optional_forward
