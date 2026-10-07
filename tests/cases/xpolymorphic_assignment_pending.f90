program xpolymorphic_assignment_pending
implicit none
type :: base
   integer :: id
end type base
type, extends(base) :: child
   integer, allocatable :: values(:)
end type child
type(base) :: plain
type(child) :: extended
class(base), allocatable :: x, y

plain%id = 10
extended%id = 20
extended%values = [1, 2, 3]
x = plain
select type (x)
type is (base)
   print *, x%id == 10
class default
   print *, .false.
end select

x = extended
select type (x)
type is (child)
   print *, x%id == 20, all(x%values == [1, 2, 3])
class default
   print *, .false., .false.
end select
y = x
select type (y)
type is (child)
   y%values(2) = 99
   print *, all(y%values == [1, 99, 3])
class default
   print *, .false.
end select
select type (x)
type is (child)
   print *, all(x%values == [1, 2, 3])
class default
   print *, .false.
end select
print *, all(extended%values == [1, 2, 3])

x = plain
y = x
select type (y)
type is (base)
   print *, y%id == 10
class default
   print *, .false.
end select
end program xpolymorphic_assignment_pending
