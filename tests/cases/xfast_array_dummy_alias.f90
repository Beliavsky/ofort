program xfast_array_dummy_alias
  implicit none
  real(kind=8) :: x(2,2)
  x = 1.0d0
  call update(x)
  print *, x(1,1), x(2,2)
contains
  subroutine update(a)
    real(kind=8), intent(inout) :: a(2,2)
    a(1,1) = a(1,1) + 2.0d0
    a(2,2) = a(1,1) + 3.0d0
  end subroutine update
end program xfast_array_dummy_alias
