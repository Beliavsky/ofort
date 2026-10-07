program xoverlap_reverse_pending
implicit none
integer :: a(6)
a = [1, 2, 3, 4, 5, 6]
a = a(6:1:-1)
print *, a
a = [1, 2, 3, 4, 5, 6]
a(1:5:2) = a(5:1:-2)
print *, a
a = [1, 2, 3, 4, 5, 6]
a(2:6:2) = a(1:5:2) + a(6:2:-2)
print *, a
end program xoverlap_reverse_pending
