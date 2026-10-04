program main
  real :: x(5)
  x = [-2.0, -1.0, 0.0, 1.0, 2.0]
  print "(5f10.6)", erf(x)
  print "(5f10.6)", erfc(x)
end program main
