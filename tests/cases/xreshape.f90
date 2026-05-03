program xreshape
! Demonstrates the Fortran reshape intrinsic.
implicit none

integer, parameter :: nsrc = 12
integer, parameter :: nrow = 3
integer, parameter :: ncol = 4
integer, parameter :: nrow2 = 2
integer, parameter :: ncol2 = 5
integer, parameter :: nplane = 2
integer, parameter :: nchar = 6
integer, parameter :: nrow_char = 2
integer, parameter :: ncol_char = 3

integer :: src(nsrc)
integer :: a(nrow,ncol)
integer :: b(ncol,nrow)
integer :: c(nrow2,ncol2)
integer :: d(nrow,ncol)
integer :: e(nrow,ncol)
integer :: f(nrow2,ncol2)
integer :: g(nrow2,ncol2)
integer :: h(nrow2,ncol2)
integer :: arr3(nrow,ncol,nplane)
integer :: i
character(len=2) :: ch_src(nchar)
character(len=2) :: ch(nrow_char,ncol_char)

src = [(i, i=1,nsrc)]

print *, "source vector:"
print *, src

print *
print *, "1. basic reshape to shape [3,4]"
a = reshape(src, [nrow,ncol])
call print_matrix(a)

print *
print *, "fortran fills arrays in column-major order:"
print *, "a(1,1), a(2,1), a(3,1), a(1,2) = ", a(1,1), a(2,1), a(3,1), a(1,2)

print *
print *, "2. reshape to shape [4,3]"
b = reshape(src, [ncol,nrow])
call print_matrix(b)

print *
print *, "3. source too short: pad supplies extra values"
c = reshape([1,2,3,4], [nrow2,ncol2], pad=[99])
call print_matrix(c)

print *
print *, "4. pad values are recycled if needed"
f = reshape([1,2,3], [nrow2,ncol2], pad=[10,20,30])
call print_matrix(f)

print *
print *, "5. source too long: extra source elements are ignored"
g = reshape(src, [nrow2,ncol2])
call print_matrix(g)

print *
print *, "6. order changes which result dimensions vary fastest"
print *, "default order [1,2]:"
d = reshape(src, [nrow,ncol])
call print_matrix(d)

print *
print *, "order [2,1]:"
e = reshape(src, [nrow,ncol], order=[2,1])
call print_matrix(e)

print *
print *, "7. reshape can create arrays of rank greater than 2"
arr3 = reshape(src, [nrow,ncol,nplane], pad=[0])
print *, "arr3(:,:,1):"
call print_matrix(arr3(:,:,1))
print *, "arr3(:,:,2):"
call print_matrix(arr3(:,:,2))

print *
print *, "8. reshape works with character arrays"
ch_src = ["aa","bb","cc","dd","ee","ff"]
ch = reshape(ch_src, [nrow_char,ncol_char])
call print_char_matrix(ch)

print *
print *, "9. reshape result can be assigned to an array section"
h = 0
h(:,2:4) = reshape([11,12,13,14,15,16], [nrow2,3])
call print_matrix(h)

contains

subroutine print_matrix(x)
! Prints an integer matrix row by row.
integer, intent(in) :: x(:,:)
integer :: i

do i = 1, size(x,1)
   print "(*(i6))", x(i,:)
end do

end subroutine print_matrix

subroutine print_char_matrix(x)
! Prints a character matrix row by row.
character(len=*), intent(in) :: x(:,:)
integer :: i

do i = 1, size(x,1)
   print "(*(a4))", x(i,:)
end do

end subroutine print_char_matrix

end program xreshape
