program xsplit_intrinsic
implicit none
character(len=30) :: s
integer :: p

s = "alpha,beta/gamma"
call split(s, ",/", p)
print *, p
call split(s, ",/", p, back=.true.)
print *, p
call split(string=s, set="/", pos=p)
print *, p
call split(s, ";", p)
print *, p
end program xsplit_intrinsic
