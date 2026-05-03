integer :: i
i = 1
if (1.eq.1) i = 2
print *, i
if (1.eq.2) i = 3
print *, i
if (1.e0 .eq. 1.0) print *, 4
if (1.d0.eq.1.0d0) print *, 5
end
