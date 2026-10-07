program xderived_copy_overlap_pending
implicit none
type :: payload
   integer :: tag
   integer, allocatable :: values(:)
end type payload
type(payload) :: a(3), b(3)
integer :: i

do i = 1, 3
   a(i)%tag = i
   allocate(a(i)%values(i))
   a(i)%values = 10*i
end do
b = a
a = a(3:1:-1)
print *, a(1)%tag == 3, a(2)%tag == 2, a(3)%tag == 1
print *, size(a(1)%values) == 3, size(a(2)%values) == 2, size(a(3)%values) == 1
print *, all(a(1)%values == 30), all(a(2)%values == 20), all(a(3)%values == 10)
a(1)%values(1) = 99
print *, all(b(3)%values == 30), a(1)%values(1) == 99

a(2:3) = a(1:2)
print *, a(1)%tag == 3, a(2)%tag == 3, a(3)%tag == 2
print *, size(a(2)%values) == 3, size(a(3)%values) == 2
print *, all(a(2)%values == [99, 30, 30]), all(a(3)%values == 20)
a(2)%values(1) = 88
print *, a(1)%values(1) == 99, a(2)%values(1) == 88
end program xderived_copy_overlap_pending
