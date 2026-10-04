program xassumed_rank_pending
implicit none
real :: s
real :: v(3)
real :: m(2,2)
s = 1.0
v = [1.0, 2.0, 3.0]
m = reshape([1.0, 2.0, 3.0, 4.0], shape(m))
call show_rank(s)
call show_rank(v)
call show_rank(m)
contains
subroutine show_rank(x)
  real :: x(..)
  print *, rank(x)
end subroutine show_rank
end program xassumed_rank_pending
