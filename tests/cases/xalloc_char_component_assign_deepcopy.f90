program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x, y
allocate(character(len=3) :: x%s)
x%s = "abc"
y = x
x%s = "zzz"
print *, allocated(y%s), len(y%s), y%s
end program main
