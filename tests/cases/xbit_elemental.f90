program xbit_elemental
implicit none
integer :: a(4), b(4), pos(4), sh(4), len(4)
logical :: tf(4)

a = [1, 2, 3, 4]
b = [4, 3, 2, 1]
pos = [0, 1, 0, 2]
sh = [0, 1, -1, 2]
len = [1, 2, 2, 1]
tf = [.true., .false., .true., .false.]

print *, not(a)
print *, iand(a, b)
print *, iand(a, 1)
print *, ior(8, a)
print *, ieor(a, b)
print *, ibclr(a, pos)
print *, ibset(a, pos)
print *, ibits(a, pos, len)
print *, ishft(a, sh)
print *, ishft(1, [0, 1, 2, 3])
print *, ishftc(a, sh, [1, 2, 3, 4])
print *, ishftc(a, sh)
print *, shiftl(1, [0, 1, 2, 3])
print *, shiftr(a, [0, 1, 1, 2])
print *, popcnt(a)
print *, poppar(a)
print *, leadz(a)
print *, trailz(a)
print *, .not. tf
end program xbit_elemental
