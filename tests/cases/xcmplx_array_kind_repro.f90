program cmplx_array_kind_repro
implicit none
integer, parameter :: dp=kind(1.0d0)
real(dp) :: x(2,2), y(2,2)
complex(dp) :: z(2,2)
x=reshape([1.000000000001_dp,2.0_dp,3.0_dp,4.0_dp],[2,2])
y=-x
z=cmplx(x,y,dp)
print *, all(shape(z)==[2,2])
print *, kind(z)==dp
print *, all(real(z,dp)==x)
print *, all(aimag(z)==y)
print *, kind(real(z))==dp
print *, all(real(z)==x)
z=cmplx(x,kind=dp)
print *, all(real(z,dp)==x) .and. all(aimag(z)==0.0_dp)
end program
