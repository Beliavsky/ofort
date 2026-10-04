program main
implicit none
type :: t
   character(:), allocatable :: s
end type t
type(t) :: x
allocate(x%s, source="abcdef")
print *, allocated(x%s), len(x%s), x%s
end program main
