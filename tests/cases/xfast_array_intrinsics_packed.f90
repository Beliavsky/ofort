integer, parameter :: dp = kind(1.0d0)
real(dp) :: a(2,2), b(2,2), v(2), w(2), x(4), y(4), vec(3)
logical :: mask(4)

a = reshape([1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp], shape(a))
b = reshape([5.0_dp, 6.0_dp, 7.0_dp, 8.0_dp], shape(b))
v = [10.0_dp, 20.0_dp]
w = [2.0_dp, 3.0_dp]
x = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]
y = [5.0_dp, 6.0_dp, 7.0_dp, 8.0_dp]
vec = [9.0_dp, 8.0_dp, 7.0_dp]
mask = [.true., .false., .true., .false.]

print *, matmul(a, b)
print *, matmul(a, v)
print *, matmul(w, a)
print *, transpose(a)
print *, pack(x, mask, vec)
print *, unpack([11.0_dp, 22.0_dp], mask, y)
print *, merge(x, y, mask)
print *, spread(v, 2, 2)
print *, eoshift(x, 1, boundary=-1.0_dp)
print *, cshift(x, 1)
print *, count(mask), any(mask), all(mask)
end
