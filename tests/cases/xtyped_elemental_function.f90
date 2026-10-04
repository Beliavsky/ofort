program xtyped_elemental_function
implicit none
print *, area(3, 4)
print *, area(3, [4, 5])
print *, area([3, 4], [4, 5])
contains
integer elemental function area(length, width)
integer, intent(in) :: length, width
area = length*width
end function area
end program xtyped_elemental_function
