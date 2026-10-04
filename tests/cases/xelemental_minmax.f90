real :: a(3), b(3), c(3)
a = [1.0, 5.0, 3.0]
b = [2.0, 4.0, 6.0]
c = max(a,b)
print *, c
c = min(a,b)
print *, c
c = max(a, 4.0)
print *, c
end
