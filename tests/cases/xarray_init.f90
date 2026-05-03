program xarray_init
  implicit none
  integer :: a(2) = (/ 1, 2 /)
  real(kind=8), parameter :: b(2) = (/ 1.5d0, 2.5d0 /)
  print *, a(1), a(2), b(1), b(2)
end program xarray_init
