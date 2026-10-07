program xderived_copy_pointer_pending
implicit none
type :: view
   integer, pointer :: values(:) => null()
   integer, allocatable :: owned(:)
end type view
integer, target :: data(6) = [1, 2, 3, 4, 5, 6]
type(view) :: a, b

a%values(-1:) => data(2:6:2)
a%owned = [10, 20, 30]
b = a
print *, associated(b%values, a%values)
print *, lbound(b%values, 1) == -1, ubound(b%values, 1) == 1
print *, all(b%values == [2, 4, 6])
b%values(0) = 40
b%owned(2) = 200
print *, all(data == [1, 2, 3, 40, 5, 6])
print *, a%values(0) == 40, all(a%owned == [10, 20, 30])
nullify(a%values)
print *, .not. associated(a%values), associated(b%values, data(2:6:2))
b%values(1) = 60
print *, all(data == [1, 2, 3, 40, 5, 60])
b = a
print *, .not. associated(b%values), all(b%owned == [10, 20, 30])
end program xderived_copy_pointer_pending
