implicit none
type(integer(8)) :: a
a = 3
if (kind(a) /= 8) print *, 101
print *, 'pass'
end
