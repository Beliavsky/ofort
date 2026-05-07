type t
  integer :: i = 7
end type
implicit type(t) (a-b)
print *, a%i
a%i = 11
print *, a%i
b = t(4)
print *, b%i
end
