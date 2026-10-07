program xoverlap_shift_pending
implicit none
integer :: a(6)
a = [1, 2, 3, 4, 5, 6]
a(2:6) = a(1:5)
print *, a
a = [1, 2, 3, 4, 5, 6]
a(1:5) = a(2:6)
print *, a
a = [1, 2, 3, 4, 5, 6]
a(2:6) = a(1:5) + 10*a(2:6)
print *, a
end program xoverlap_shift_pending
