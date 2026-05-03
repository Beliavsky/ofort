program xassociated
implicit none

integer, parameter :: n = 5

integer, target :: a(n)
integer, target :: b(n)
integer, pointer :: p(:)
integer, pointer :: q(:)
integer, pointer :: r
integer, target :: x

a = [1, 2, 3, 4, 5]
b = [10, 20, 30, 40, 50]
x = 99

nullify(p)
nullify(q)
nullify(r)

print *, "associated(pointer) tells whether a pointer is associated."
print *, "associated(pointer, target) tells whether it is associated with target."
print *

print *, "after nullify:"
print *, "associated(p) =", associated(p)
print *, "associated(q) =", associated(q)
print *, "associated(r) =", associated(r)
print *

p => a
q => a
r => x

print *, "after p => a, q => a, r => x:"
print *, "associated(p) =", associated(p)
print *, "associated(q) =", associated(q)
print *, "associated(r) =", associated(r)
print *

print *, "target tests:"
print *, "associated(p, a) =", associated(p, a)
print *, "associated(p, b) =", associated(p, b)
print *, "associated(q, a) =", associated(q, a)
print *, "associated(r, x) =", associated(r, x)
print *

print *, "pointer-to-pointer target tests:"
print *, "associated(p, q) =", associated(p, q)

q => b
print *
print *, "after q => b:"
print *, "associated(p, q) =", associated(p, q)
print *, "associated(q, b) =", associated(q, b)
print *

p => a(2:4)
print *, "after p => a(2:4):"
print *, "p =", p
print *, "associated(p) =", associated(p)
print *, "associated(p, a) =", associated(p, a)
print *, "associated(p, a(2:4)) =", associated(p, a(2:4))
print *

nullify(p)
print *, "after nullify(p):"
print *, "associated(p) =", associated(p)

end program xassociated
