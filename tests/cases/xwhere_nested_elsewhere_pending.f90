program xwhere_nested_elsewhere_pending
implicit none
integer :: a(0:1, -1:1), b(2, 3)

! Every printed logical value should be T.
a = reshape([1, 2, 3, 4, 5, 6], [2, 3])
b = -99
where (mod(a, 2) == 0)
    where (a > 3)
        b = 100 + a
    elsewhere
        b = 200 + a
    end where
elsewhere (a <= 3)
    b = -a
elsewhere
    b = 0
end where
print *, all(b == reshape([-1, 202, -3, 104, 0, 106], [2, 3]))

! An ELSEWHERE mask must exclude elements selected by earlier branches.
b = -99
where (a <= 2)
    b = 10 + a
elsewhere (a <= 4)
    b = 20 + a
elsewhere (a <= 6)
    b = 30 + a
end where
print *, all(b == reshape([11, 12, 23, 24, 35, 36], [2, 3]))
end program xwhere_nested_elsewhere_pending
