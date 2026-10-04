module m
implicit none
interface show
   module procedure show_vec, show_mat
end interface
contains
subroutine show_vec(x, n, fmt, iu, horizontal)
real, intent(in) :: x(:)
integer, intent(in), optional :: n
character(len=*), intent(in), optional :: fmt
integer, intent(in), optional :: iu
logical, intent(in), optional :: horizontal
if (present(horizontal)) print *, "vec", present(horizontal), horizontal
end subroutine
subroutine show_mat(x, n, fmt, iu)
real, intent(in) :: x(:,:)
integer, intent(in), optional :: n
character(len=*), intent(in), optional :: fmt
integer, intent(in), optional :: iu
print *, "mat"
end subroutine
end module

program main
use m, only: show
implicit none
real :: x(2)
x = [1.0, 2.0]
call show(x, n=1, fmt="header", horizontal=.true.)
end program
