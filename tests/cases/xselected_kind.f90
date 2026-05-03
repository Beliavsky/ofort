program xselected_kinds
implicit none

integer, parameter :: n_int = 6
integer, parameter :: n_real = 6

integer :: i
integer :: int_digits(n_int)
integer :: real_prec(n_real)
integer :: real_range(n_real)
integer :: ik
integer :: rk

int_digits = [1, 2, 4, 9, 18, 30]
real_prec  = [3, 6, 12, 15, 30, 100]
real_range = [10, 30, 100, 300, 3000, 10000]

print *, "selected_int_kind(r) returns an integer kind with decimal exponent range >= r."
print *, "negative results mean no such kind exists."
print *

print *, "selected_int_kind examples:"
do i = 1, n_int
   ik = selected_int_kind(int_digits(i))
   print *, "r =", int_digits(i), " selected_int_kind(r) =", ik
end do
print *

print *, "selected_real_kind(p, r) returns a real kind with precision >= p and range >= r."
print *, "negative results mean no such kind exists."
print *

print *, "selected_real_kind with precision only:"
do i = 1, n_real
   rk = selected_real_kind(p=real_prec(i))
   print *, "p =", real_prec(i), " selected_real_kind(p=p) =", rk
end do
print *

print *, "selected_real_kind with range only:"
do i = 1, n_real
   rk = selected_real_kind(r=real_range(i))
   print *, "r =", real_range(i), " selected_real_kind(r=r) =", rk
end do
print *

print *, "selected_real_kind with precision and range:"
do i = 1, n_real
   rk = selected_real_kind(p=real_prec(i), r=real_range(i))
   print *, "p =", real_prec(i), " r =", real_range(i), &
            " selected_real_kind(p=p, r=r) =", rk
end do
print *

print *, "using the returned kinds:"
ik = selected_int_kind(9)
rk = selected_real_kind(p=15, r=300)

print *, "ik =", ik
print *, "rk =", rk

if (ik > 0) then
   print *, "range(0_ik) cannot be written directly because kind values in literals"
   print *, "must be compile-time constants, not variables."
end if

if (rk > 0) then
   print *, "similarly, 1.0_rk is not valid when rk is an ordinary variable."
end if

end program xselected_kinds
