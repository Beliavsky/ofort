program main
implicit none
character(:), allocatable :: s
s = "abc"
print *, allocated(s), len(s), s
s = "abcdef"
print *, allocated(s), len(s), s
end program main
