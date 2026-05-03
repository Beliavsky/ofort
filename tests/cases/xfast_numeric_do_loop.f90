program xfast_numeric_do_loop
  implicit none
  integer :: i, j, k
  real(kind=8) :: a(2,3), s
  k = 0
  do j = 1, 3
     do i = 1, 2
        k = k + 1
        a(i,j) = k * 2.0d0
     end do
  end do
  s = 0.0d0
  do j = 1, 3
     do i = 1, 2
        s = s + a(i,j)
     end do
  end do
  print *, k, s
end program xfast_numeric_do_loop
