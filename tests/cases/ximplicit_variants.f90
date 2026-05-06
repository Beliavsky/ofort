implicit character(d), integer(a-c, e-z)
d = 'xy'
a = 3
if (len(d) /= 1) print *, 101
if (a /= 3) print *, 102

call old_style
call kind_style
print *, 'pass'

contains
subroutine old_style
  implicit character*2 (a)
  aa = 'xyz'
  if (len(aa) /= 2) print *, 201
end subroutine

subroutine kind_style
  implicit real(kind(1d0)) (r)
  r = 1.5
  if (r /= 1.5) print *, 301
end subroutine
end
