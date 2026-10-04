program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x, y
allocate(character(len=5) :: x%s)
allocate(character(len=2) :: y%s)
x%s = "abcde"
y%s = "zz"
y = x
print *, allocated(y%s), len(y%s), y%s
end program main
