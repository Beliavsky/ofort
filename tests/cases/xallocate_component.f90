type tag
  complex, pointer :: c
end type
type(tag) :: st
allocate(st%c)
st%c = (1.0, 2.0)
print *, st%c
call set_component(st%c)
print *, st%c
deallocate(st%c)
print *, "OK"
contains
subroutine set_component(c)
  complex :: c
  c = (3.0, 4.0)
end subroutine
