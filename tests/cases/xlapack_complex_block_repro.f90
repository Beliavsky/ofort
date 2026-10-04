program complex_block_repro
implicit none
integer, parameter :: dp=kind(1.0d0), n=2
complex(dp) :: a(n,n), b(n)
real(dp) :: ac(2*n,2*n), bc(2*n,1)
integer :: ipiv(2*n), info, j
a = cmplx(0.0_dp,0.0_dp,dp)
a(1,1)=cmplx(4.0_dp,0.5_dp,dp)
a(2,2)=cmplx(4.0_dp,0.0_dp,dp)
a(1,2)=cmplx(1.0_dp,0.0_dp,dp)
a(2,1)=cmplx(1.0_dp,0.0_dp,dp)
b = cmplx([1.0_dp,2.0_dp],[-1.0_dp,-2.0_dp],dp)
ac(1:n,1:n)=real(a,dp)
ac(1:n,n+1:2*n)=-aimag(a)
ac(n+1:2*n,1:n)=aimag(a)
ac(n+1:2*n,n+1:2*n)=real(a,dp)
bc(1:n,1)=real(b,dp)
bc(n+1:2*n,1)=aimag(b)
do j=1,2*n
 print *, ac(:,j)
end do
call dgesv(2*n,1,ac,2*n,ipiv,bc,2*n,info)
print *, 'info',info
print *, bc(:,1)
end program
