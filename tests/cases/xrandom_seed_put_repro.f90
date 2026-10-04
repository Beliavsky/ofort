program seed_put_repro
implicit none
integer :: n
integer, allocatable :: seed(:)
real(kind=kind(1.0d0)) :: x(4), y(4)
call random_seed(size=n)
allocate(seed(n))
seed=12345
call random_seed(put=seed)
call random_number(x)
call random_seed(put=seed)
call random_number(y)
print *, all(x==y)
end program
