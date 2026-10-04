program xderived_array_parameter_dim
implicit none
type :: t
  integer :: k
end type
integer, parameter :: n = 10
type(t), dimension(n) :: a
a = t(0)
a(1)%k = 7
a(10)%k = 3
print *, size(a), a(1)%k, a(10)%k
end program xderived_array_parameter_dim
