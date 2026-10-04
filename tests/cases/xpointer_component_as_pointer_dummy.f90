program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
integer, target :: a(3)
a = [1, 2, 3]
x%p => a
call set_second(x%p)
print *, a
contains
subroutine set_second(p)
integer, pointer, intent(inout) :: p(:)
p(2) = 77
end subroutine set_second
end program main
