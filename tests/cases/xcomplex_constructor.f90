implicit none
integer :: i
complex :: z(2), w(3)
z = [ (1.0,2.0), (3.0,4.0) ]
w = [(cmplx(i, -i), i=1,3)]
print *, z
print *, w
end
