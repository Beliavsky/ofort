type tag
  integer :: i
end type
type(tag) :: call
call%i = 7
print *, call%i
