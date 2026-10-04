program main
implicit none
type :: holder
   character(:), allocatable :: s
end type holder
type(holder) :: h
h%s = "abc"
print *, allocated(h%s), len(h%s), h%s
h%s = "abcdef"
print *, allocated(h%s), len(h%s), h%s
end program main
