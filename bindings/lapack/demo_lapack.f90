program demo_lapack
   use, intrinsic :: iso_fortran_env, only: real64
   use ofort_lapack_mod, only: dgesv, dsyev
   implicit none
   real(real64) :: a(2,2), b(2), eigenvalues(2)
   real(real64), allocatable :: work(:)
   integer :: ipiv(2), info, lwork

   a = reshape([2.0_real64, 1.0_real64, 1.0_real64, 3.0_real64], [2,2])
   b = [4.0_real64, 7.0_real64]
   call dgesv(2, 1, a, 2, ipiv, b, 2, info)
   if (info /= 0) error stop 'DGESV failed'
   print '(a,2f12.6)', 'Solution: ', b

   a = reshape([2.0_real64, 1.0_real64, 1.0_real64, 3.0_real64], [2,2])
   allocate(work(1))
   call dsyev('N', 'U', 2, a, 2, eigenvalues, work, -1, info)
   if (info /= 0) error stop 'DSYEV workspace query failed'
   lwork = max(1, int(work(1)))
   deallocate(work)
   allocate(work(lwork))
   call dsyev('N', 'U', 2, a, 2, eigenvalues, work, lwork, info)
   if (info /= 0) error stop 'DSYEV failed'
   print '(a,2f12.6)', 'Eigenvalues: ', eigenvalues
end program demo_lapack
