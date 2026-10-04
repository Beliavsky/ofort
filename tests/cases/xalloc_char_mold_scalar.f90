program main
implicit none
character(:), allocatable :: s, t
allocate(character(len=7) :: s)
s = "abcdefg"
allocate(t, mold=s)
t = "xy"
print *, allocated(t), len(t), "'" // t // "'"
end program main
