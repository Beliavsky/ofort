program main
implicit none
integer, target :: x
x = 6
call s(x)
print *, x
contains
pure subroutine s(a)
integer, target, intent(in) :: a
integer, pointer :: p
p => a
p = 60
end subroutine s
end program main
