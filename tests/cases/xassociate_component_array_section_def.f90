program main
implicit none
type :: t
   integer :: v(4)
end type t
type(t), target :: x
x%v = [1, 2, 3, 4]
associate (a => x%v(2:4:2))
   a = a * 10
end associate
print *, x%v
end program main
