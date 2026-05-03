type tag
  complex, pointer :: c
end type
type(tag) :: st
complex :: x
x = (1.0, 2.0)
st%c => x
call set_component(st%c)
print *, st%c
contains
subroutine set_component(c)
  complex :: c
  c = (3.0, 4.0)
end subroutine
