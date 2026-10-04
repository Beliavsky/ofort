program main
implicit none
integer :: x
x = 4
call s(x)
print *, x
contains
subroutine s(a)
integer, intent(in) :: a
associate (b => a)
   b = 40
end associate
end subroutine s
end program main
