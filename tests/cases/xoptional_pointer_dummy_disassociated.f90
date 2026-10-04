program main
implicit none
integer, pointer :: p(:) => null()
call show(p)
contains
subroutine show(p)
integer, pointer, optional, intent(inout) :: p(:)
print *, present(p), associated(p)
end subroutine show
end program main
