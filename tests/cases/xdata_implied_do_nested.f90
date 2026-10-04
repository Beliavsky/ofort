integer :: a1(1,1)
integer :: a2(2)
integer :: k1, k2, k3

data ((a1(k1,k2), k1 = 1, 1), k2 = 1, 1) /1/
data (a2(k3), k3 = 1, 2) /2, 3/

if (a1(1,1) /= 1) print *, 101
if (a2(1) /= 2) print *, 102
if (a2(2) /= 3) print *, 103
print *, 'pass'
end
