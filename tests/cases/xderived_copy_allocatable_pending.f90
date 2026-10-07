program xderived_copy_allocatable_pending
implicit none
type :: payload
   integer, allocatable :: values(:)
   character(len=:), allocatable :: label
end type payload
type(payload) :: a, b, empty

allocate(a%values(0:2))
a%values = [10, 20, 30]
a%label = "original"
b = a
print *, allocated(b%values), allocated(b%label)
print *, lbound(b%values, 1) == 0, ubound(b%values, 1) == 2
print *, all(b%values == [10, 20, 30]), b%label == "original"

b%values(1) = 99
b%label = "copy"
print *, all(a%values == [10, 20, 30]), a%label == "original"
deallocate(a%values)
a%label = "changed"
print *, all(b%values == [10, 99, 30]), b%label == "copy"

allocate(a%values(4:5))
a%values = [40, 50]
b = a
print *, size(b%values) == 2, all(b%values == [40, 50])
print *, len(b%label) == 7, b%label == "changed"
b = empty
print *, .not. allocated(b%values), .not. allocated(b%label)
print *, allocated(a%values), allocated(a%label)
end program xderived_copy_allocatable_pending
