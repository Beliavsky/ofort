module access_mod
implicit none
private
public :: i, k, n, set_var
integer :: i, j
integer, protected :: k
integer, parameter :: n = 8
contains
subroutine set_var()
i = 2
j = 3
k = 4
end subroutine set_var
end module access_mod

program test_access
use access_mod
implicit none
character (len=*), parameter :: fmt = "(a,*(1x,i0))"
call set_var()
print fmt,"i, k =",i,k
i = 5
print fmt,"i =",i
end program test_access
