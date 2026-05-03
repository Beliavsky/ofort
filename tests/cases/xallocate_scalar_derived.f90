type tag
  complex :: c
end type
type(tag), pointer :: p
type(tag), allocatable :: a
allocate(p)
allocate(a)
p%c = (1.0, 2.0)
a%c = (3.0, 4.0)
call set_tag(p)
call set_tag(a)
print *, p%c, a%c
deallocate(p)
deallocate(a)
print *, "OK"
contains
subroutine set_tag(x)
  type(tag) :: x
  x%c = x%c + (1.0, 1.0)
end subroutine
