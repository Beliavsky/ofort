program sequence_disjoint_outputs
implicit none
double precision :: a(5), work(12)
a = 1d0
call reflector(a(4), a(1))
print *, a(4) == -2d0
print *, all(abs(a(1:3) - 1d0/3d0) < 1d-14)
work = 0d0
call workspace(work(1), work(5), work(9))
print *, all(work(1:4) == 2d0)
print *, all(work(5:8) == 3d0)
print *, all(work(9:12) == 4d0)
contains
subroutine reflector(alpha, x)
double precision :: alpha, x(*)
alpha = -2d0
x(1:3) = 1d0/3d0
end subroutine
subroutine workspace(d, e, tau)
double precision :: d(*), e(*), tau(*)
d(1:4) = 2d0
e(1:4) = 3d0
tau(1:4) = 4d0
end subroutine
end program
