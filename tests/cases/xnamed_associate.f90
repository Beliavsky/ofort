integer :: i
i = 3
outer: associate (a => i)
  if (a /= 3) print *, 101
end associate outer
print *, 'pass'
end
