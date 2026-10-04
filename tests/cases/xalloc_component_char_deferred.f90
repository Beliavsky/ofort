program main
implicit none
type :: holder
   character(:), allocatable :: s(:)
end type holder
type(holder) :: h
integer :: stat
character(len=100) :: msg
msg = ""
allocate(character(len=4) :: h%s(2), stat=stat, errmsg=msg)
h%s = [character(len=4) :: "ab", "cdef"]
print *, stat, trim(msg), allocated(h%s), len(h%s), size(h%s), h%s(1) == "ab  ", h%s(2) == "cdef"
end program main
