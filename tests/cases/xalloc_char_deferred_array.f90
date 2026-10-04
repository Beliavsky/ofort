program main
implicit none
character(:), allocatable :: s(:)
allocate(character(len=4) :: s(2))
s = [character(len=4) :: "ab", "cdef"]
print *, allocated(s), len(s), size(s), s(1) == "ab  ", s(2) == "cdef"
deallocate(s)
end program main
