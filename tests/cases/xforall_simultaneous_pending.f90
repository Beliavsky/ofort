program xforall_simultaneous_pending
implicit none
integer :: a(6), b(6), matrix(2, 3), i, j

! Every printed logical value should be T.
! FORALL assignments are simultaneous, unlike sequential DO iterations.
a = [1, 2, 3, 4, 5, 6]
forall (i=1:6)
    a(i) = a(7-i)
end forall
print *, all(a == [6, 5, 4, 3, 2, 1])

! All iterations of the first assignment finish before the second begins.
a = [1, 2, 3, 4, 5, 6]
b = 0
forall (i=1:6)
    a(i) = a(7-i)
    b(i) = a(i) + a(7-i)
end forall
print *, all(a == [6, 5, 4, 3, 2, 1]), all(b == 7)

! The header mask is captured before assignments modify A.
a = [1, 2, 3, 4, 5, 6]
b = 0
forall (i=1:6, a(i) <= 3)
    a(i) = a(i) + 10
    b(i) = a(i)
end forall
print *, all(a == [11, 12, 13, 4, 5, 6])
print *, all(b == [11, 12, 13, 0, 0, 0])

matrix = reshape([1, 2, 3, 4, 5, 6], [2, 3])
forall (i=1:2, j=1:3)
    matrix(i, j) = matrix(3-i, 4-j)
end forall
print *, all(matrix == reshape([6, 5, 4, 3, 2, 1], [2, 3]))
end program xforall_simultaneous_pending
