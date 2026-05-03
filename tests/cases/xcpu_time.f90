program xcpu_time
implicit none

real :: t0, t1
integer :: i
real :: s

print *, "cpu_time returns CPU time in seconds."
print *

call cpu_time(t0)

s = 0.0
do i = 1, 1000000
   s = s + 1.0
end do

call cpu_time(t1)

print *, "result s =", s
print *, "CPU time =", t1 - t0, "seconds"

end program xcpu_time
