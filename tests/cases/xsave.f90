module counter_mod
implicit none

contains

subroutine count_calls()
   ! Prints how many times this procedure has been called.
   integer, save :: ncall = 0
   integer :: mcall = 0
   ncall = ncall + 1
   mcall = mcall + 1
   print *, "count_calls has been called", ncall, mcall, "time(s)"
end subroutine count_calls

end module counter_mod

program xsave
use counter_mod, only: count_calls
implicit none

call count_calls()
call count_calls()
call count_calls()

end program xsave
