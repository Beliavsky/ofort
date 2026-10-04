module m
implicit none
type :: item
   character(len=20) :: title
end type
contains
pure function scaled(x, factor) result(y)
type(item), intent(in) :: x
real, intent(in) :: factor
type(item) :: y
y = x
write(y%title, "(a,'/',f0.1)") trim(x%title), factor
end function
end module

program main
use m, only: item, scaled
implicit none
type(item) :: x, y
x%title = "abc"
y = scaled(x, 2.0)
print *, trim(y%title)
end program
