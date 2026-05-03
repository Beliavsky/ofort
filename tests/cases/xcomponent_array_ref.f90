type t
  integer :: p(3)
end type
type(t) :: x
x%p(1) = 1
x%p(2) = 2
x%p(3) = 3
print *, x%p(2)
print *, x%p(:)
x%p(2) = 9
print *, x%p
end
