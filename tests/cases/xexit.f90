implicit none
real :: x
x = 0.0
do
   call random_number(x)
   if (x > 0.9) exit
   print*,x
end do
print*,"big",x
end
