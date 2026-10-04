program xprocedure_pointer_arg_allocatable_mismatch_reject
implicit none
abstract interface
  integer function f_plain(x)
    integer, intent(in) :: x(:)
  end function f_plain
end interface
procedure(f_plain), pointer :: p
integer, allocatable :: a(:)

allocate(a(2))
a = [4, 5]
p => takes_allocatable
print *, p(a)

contains

integer function takes_allocatable(x)
  integer, allocatable, intent(in) :: x(:)
  takes_allocatable = sum(x)
end function takes_allocatable

end program xprocedure_pointer_arg_allocatable_mismatch_reject
