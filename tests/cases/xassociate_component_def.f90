program main
implicit none
type :: t
   integer :: n
end type t
type(t), target :: x
x%n = 4
associate (a => x%n)
   a = 40
end associate
print *, x%n
end program main
