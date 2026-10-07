program xpointer_alias_chain_pending
implicit none
integer, target :: a(10)
integer, pointer :: p(:), q(:)
a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
p(0:) => a(2:10:2)
q(-2:) => p(4:0:-2)
print *, lbound(q), ubound(q), q
q(-1) = 600
a(10) = 1000
print *, q
print *, a
q = [11, 22, 33]
print *, p
print *, a
end program xpointer_alias_chain_pending
