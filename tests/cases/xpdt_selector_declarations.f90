type ty(k,l,m)
  integer, kind :: k, m
  integer, len :: l
  integer :: ii
end type

type holder
  type(ty(:,:,:)), allocatable :: cmp
  type(ty(k=:,l=:,m=1)), pointer :: ptr
end type

type t2(k,l)
  integer, kind :: k
  integer, len :: l
end type

type t1
  type(t2(4,:)), allocatable :: cmp1
end type

print *, 'pass'
end
