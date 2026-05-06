integer :: i, s
s = 0
do 10, concurrent(i=1:4)
  s = s + i
10 continue
if (s /= 10) print *, 101
print *, 'pass'
end
