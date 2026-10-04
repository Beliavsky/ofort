program main
implicit none
type :: holder
   character(:), allocatable :: s(:)
end type holder
type(holder) :: h
character(len=4) :: source(2)
source = [character(len=4) :: "ab", "cdef"]
allocate(h%s, source=source)
print *, allocated(h%s), len(h%s), size(h%s), h%s(1) == "ab  ", h%s(2) == "cdef"
end program main
