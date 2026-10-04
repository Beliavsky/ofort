program main
implicit none
type :: t
   integer, pointer :: p(:) => null()
end type t
type(t) :: x
call show(x%p)
contains
subroutine show(p)
integer, pointer, optional, intent(inout) :: p(:)
print *, present(p), associated(p)
end subroutine show
end program main
