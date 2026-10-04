program xtypeof_classof
implicit none
integer(kind=8) :: i
real(kind=8) :: x
character(len=5) :: s
logical(kind=1) :: flag
typeof(i) :: j
classof(x) :: y
typeof(s) :: t
classof(flag) :: ok
i = 7
x = 2.5d0
s = "abc"
flag = .true.
j = i + 1
y = x + 1.0d0
t = s
ok = flag
print *, kind(j), j
print *, kind(y), y
print *, len(t), trim(t)
print *, kind(ok), ok
end program xtypeof_classof
