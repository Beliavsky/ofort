module m
implicit none
integer, save :: n
contains
subroutine init()
implicit none
n = 0
end subroutine init
subroutine inc()
implicit none
n = n + 1
print *, n
end subroutine inc
subroutine run()
implicit none
call init()
call inc()
end subroutine run
end module m

program main
use m
implicit none
call run()
end program main
