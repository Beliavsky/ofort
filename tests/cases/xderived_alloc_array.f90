type inner
  integer, allocatable :: p(:)
end type
type outer
  type(inner), allocatable :: a(:)
end type
type(outer) :: x
type(inner), pointer :: q(:)
allocate(x%a(2))
allocate(x%a(1)%p(2))
x%a(1)%p = [4, 5]
print *, x%a(1)%p(2)
allocate(q(1))
allocate(q(1)%p(1))
q(1)%p(1) = 7
print *, q(1)%p(1)
end
