program main
implicit none
character(:), allocatable :: s
allocate(s, source="abcdef")
print *, allocated(s), len(s), "'" // s // "'"
end program main
