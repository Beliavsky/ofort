program main
implicit none
integer :: v(3)
v = [1, 2, 3]
call s(v)
print *, v
contains
subroutine s(a)
integer, intent(in) :: a(:)
a(2) = 20
end subroutine s
end program main
