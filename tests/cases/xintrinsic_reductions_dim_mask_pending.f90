program xintrinsic_reductions_dim_mask_pending
implicit none
integer :: a(0:1, -1:1), empty(0, 3)
logical :: mask(2, 3)

! Every printed logical value should be T.
a = reshape([1, 2, 3, 4, 5, 6], [2, 3])
mask = mod(a, 2) == 0
print *, all(sum(a, dim=1) == [3, 7, 11])
print *, all(sum(a, dim=2) == [9, 12])
print *, all(sum(a, dim=1, mask=mask) == [2, 4, 6])
print *, all(sum(a, dim=2, mask=mask) == [0, 12])
print *, all(product(a, dim=1) == [2, 12, 30])
print *, all(product(a, dim=2, mask=mask) == [1, 48])
print *, all(count(mask, dim=1) == [1, 1, 1])
print *, all(count(mask, dim=2) == [0, 3])
print *, all(minval(a, dim=1, mask=mask) == [2, 4, 6])
print *, all(maxval(a, dim=2) == [5, 6])
print *, all(lbound(sum(a, dim=1)) == 1)

! Empty reductions must return the appropriate identity, without a read.
print *, all(sum(empty, dim=1) == 0)
print *, all(product(empty, dim=1) == 1)
print *, all(minval(empty, dim=1) == huge(0))
! On the supported two's-complement targets, the most negative integer
! has one more unit of magnitude than HUGE(0).
print *, all(maxval(empty, dim=1) == -huge(0)-1)
print *, all(minval(a, dim=1, mask=.false.) == huge(0))
print *, all(maxval(a, dim=2, mask=.false.) == -huge(0)-1)
end program xintrinsic_reductions_dim_mask_pending
