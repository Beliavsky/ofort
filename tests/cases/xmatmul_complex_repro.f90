program matmul_complex_repro
implicit none
integer, parameter :: dp=kind(1.0d0)
complex(dp) :: a(2,2), b(2,2), c(2,2), v(2), w(2)
real(dp) :: eye(2,2)
a=reshape([cmplx(1.0_dp,1.0_dp,dp),cmplx(2.0_dp,-1.0_dp,dp), &
           cmplx(3.0_dp,2.0_dp,dp),cmplx(4.0_dp,-1.0_dp,dp)],[2,2])
b=a
eye=reshape([1.0_dp,0.0_dp,0.0_dp,1.0_dp],[2,2])
c=matmul(a,b)
print *, abs(c(1,1)-(a(1,1)*b(1,1)+a(1,2)*b(2,1)))<1.0d-12
print *, abs(c(2,2)-(a(2,1)*b(1,2)+a(2,2)*b(2,2)))<1.0d-12
print *, kind(matmul(a,b))==dp
print *, all(abs(matmul(a,eye)-a)<1.0d-12)
v=[cmplx(1.0_dp,2.0_dp,dp),cmplx(3.0_dp,-1.0_dp,dp)]
w=matmul(a,v)
print *, abs(w(1)-(a(1,1)*v(1)+a(1,2)*v(2)))<1.0d-12
w=matmul(v,a)
print *, abs(w(2)-(v(1)*a(1,2)+v(2)*a(2,2)))<1.0d-12
print *, all(abs(matmul(eye,a)-a)<1.0d-12)
end program
