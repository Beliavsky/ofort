program main
use stdlib_linalg, only: eye, diag, trace, outer_product, is_square, is_diagonal, is_symmetric
implicit none
real(8) :: a(2,2), v(3), w(2)

a(1,1) = 1.0d0
a(2,1) = 2.0d0
a(1,2) = 2.0d0
a(2,2) = 4.0d0
v = [1.0d0, 2.0d0, 3.0d0]
w = [10.0d0, 20.0d0]

print *, eye(2)
print *, eye(2, 3)
print *, diag(v)
print *, diag(diag(v))
print *, diag(a, 1)
print *, trace(a)
print *, outer_product(v, w)
print *, is_square(a), is_diagonal(diag(v)), is_diagonal(a), is_symmetric(a)
end program main
