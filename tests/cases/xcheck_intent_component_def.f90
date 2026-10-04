program main
implicit none
type :: t
   integer :: n
end type t
type(t) :: x
x%n = 3
call s(x)
print *, x%n
contains
subroutine s(a)
type(t), intent(in) :: a
a%n = 30
end subroutine s
end program main
