program xreduce_ordered
implicit none
integer :: a(4), s
a = [1, 2, 3, 4]
s = reduce(a, add, ordered=.true.)
print *, s
s = reduce(a, add, ordered=.false.)
print *, s
contains
  integer function add(x, y)
    integer, intent(in) :: x, y
    add = x + y
  end function add
end program xreduce_ordered
