program xfast_rank2_array_expr
  implicit none
  real(kind=8) :: x(2,2), y(2,2)
  x(1,1) = 1.0d0
  x(2,1) = 3.0d0
  x(1,2) = 4.0d0
  x(2,2) = 0.0d0
  y(1,1) = 2.0d0
  y(2,1) = 7.0d0
  y(1,2) = 5.0d0
  y(2,2) = 6.0d0
  x(2,2) = x(1,1) + x(2,1) * y(1,2) - y(2,2) / 2.0d0
  print *, x(2,2)
end program xfast_rank2_array_expr
