program main
implicit none
character(:), allocatable :: s(:)
allocate(s, source=[character(len=3) :: "ab", "xyz"])
print *, allocated(s), len(s), size(s), s(1) == "ab ", s(2) == "xyz"
end program main
