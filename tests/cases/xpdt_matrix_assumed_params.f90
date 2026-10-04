module xpdt_matrix_assumed_params_mod
integer, parameter :: nlen = 20, sp = kind(1.0)

type :: data_frame(n1, n2, wp)
integer, len :: n1 = 100, n2 = 100
integer, kind :: wp = kind(1.0)
real(kind=wp) :: x(n1, n2)
character(len=nlen) :: row_names(n1), col_names(n2)
end type data_frame

contains
subroutine display(df)
type(data_frame(*, *, sp)), intent(in) :: df
integer :: i
print "(6x,*(a8))", "", df%col_names
do i = 1, df%n1
  print "(a8,*(f8.4))", df%row_names(i), df%x(i, :)
end do
end subroutine display
end module xpdt_matrix_assumed_params_mod

program xpdt_matrix_assumed_params
use xpdt_matrix_assumed_params_mod, only: data_frame, display, sp
implicit none
integer, parameter :: dp = kind(1.0d0), n1 = 2, n2 = 3
type(data_frame(n1, n2, dp)) :: df
type(data_frame) :: ds
type(data_frame(:, :, sp)), allocatable :: da

print "(a,*(1x,i0))", "shape(df%x), size(df%row_names), size(df%col_names) =", &
  shape(df%x), size(df%row_names), size(df%col_names)
print "(a,*(1x,i0))", "df%n1, df%n2, df%wp=", df%n1, df%n2, df%wp
print "(a,*(1x,i0))", "ds%n1, ds%n2, ds%wp=", ds%n1, ds%n2, ds%wp

allocate (data_frame(n1, n2, sp) :: da)
print "(a,*(1x,i0))", "shape(da%x), kind(da%x) =", shape(da%x), kind(da%x)
da%x = reshape([0.1_sp, 0.2_sp, 0.3_sp, 0.4_sp, 0.5_sp, 0.6_sp], [n1, n2])
da%row_names = ["r1", "r2"]
da%col_names = ["c1", "c2", "c3"]
call display(da)
end program xpdt_matrix_assumed_params
