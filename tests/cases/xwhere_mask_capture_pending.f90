program xwhere_mask_capture_pending
implicit none
integer :: a(6), b(6)
logical :: mask(6)

! Every printed logical value should be T.
! Changing A must not change the mask captured on entry to WHERE.
a = [1, 2, 3, 4, 5, 6]
b = 0
where (a <= 3)
    a = a + 10
    b = a
elsewhere
    b = -a
end where
print *, all(a == [11, 12, 13, 4, 5, 6])
print *, all(b == [11, 12, 13, -4, -5, -6])

! Each assignment uses an independent RHS before modifying its destination.
a = [1, 2, 3, 4, 5, 6]
mask = [.false., .true., .true., .true., .true., .false.]
where (mask)
    a = cshift(a, -1)
end where
print *, all(a == [1, 1, 2, 3, 4, 6])

! Non-elemental reductions use the entire argument, not just masked elements.
a = [1, 2, 3, 4, 5, 6]
b = -1
where (mask)
    b = sum(a)
end where
print *, all(b == [-1, 21, 21, 21, 21, -1])
end program xwhere_mask_capture_pending
