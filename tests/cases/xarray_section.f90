program xarray_section
implicit none
real :: a(2,3)
real :: b(6)
a(1,1) = 10.0
a(2,1) = 20.0
a(1,2) = 30.0
a(2,2) = 40.0
a(1,3) = 50.0
a(2,3) = 60.0
print *, a(1,:)
print *, a(:,2)
a(:,3) = 5.0
print *, a(:,3)
a(2,:) = a(1,:)
print *, a(2,:)
b(1) = 1.0
b(2) = 2.0
b(3) = 3.0
b(4) = 4.0
b(5) = 5.0
b(6) = 6.0
print *, b(2::2)
b(::2) = 9.0
print *, b
end program xarray_section
