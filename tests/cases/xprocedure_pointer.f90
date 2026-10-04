program xprocedure_pointer_pending
implicit none
abstract interface
  integer function f_int(i)
    integer, intent(in) :: i
  end function f_int
end interface
procedure(f_int), pointer :: p => null()
print *, associated(p)
p => twice
print *, associated(p), p(3)
contains
integer function twice(i)
  integer, intent(in) :: i
  twice = 2*i
end function twice
end program xprocedure_pointer_pending
