program main
implicit none
type :: t
   integer, allocatable :: x(:)
end type t
type(t) :: a
allocate(a%x(2))
a%x = [9, 8]
call reset(3, a)
print *, allocated(a%x), size(a%x), a%x
call reset(1, a)
print *, allocated(a%x), size(a%x), a%x
contains
elemental subroutine reset(n, y)
integer, intent(in) :: n
type(t), intent(out) :: y
allocate(y%x(n))
y%x = n
end subroutine reset
end program main
