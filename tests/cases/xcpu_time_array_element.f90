program xcpu_time_array_element
real :: t(2)
call cpu_time(t(1))
call cpu_time(t(2))
print *, t(1) >= 0.0, t(2) >= t(1)
end program xcpu_time_array_element
