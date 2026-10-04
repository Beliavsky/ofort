program main
implicit none
character(:), allocatable :: s
allocate(character(len=5) :: s)
s = "abc"
print *, allocated(s), len(s), "'" // s // "'"
deallocate(s)
end program main
