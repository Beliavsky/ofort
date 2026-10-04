program main
implicit none
character(:), allocatable :: s(:), t(:)
allocate(character(len=6) :: s(2))
s = [character(len=6) :: "abc", "uvwxyz"]
allocate(t, mold=s)
t = [character(len=6) :: "hi", "there"]
print *, allocated(t), len(t), size(t), t(1) == "hi    ", t(2) == "there "
end program main
