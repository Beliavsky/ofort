module xpdt_stream_alloc_dummy_mod
implicit none
integer, parameter :: nlen = 10
type :: data_frame(n1, n2)
  integer, len :: n1, n2
  character(len=nlen) :: col_names(n2)
  real :: x(n1, n2)
end type data_frame
contains
subroutine write_stream(df, iu)
type(data_frame(*, *)), intent(in) :: df
integer, intent(in) :: iu
write (iu) df%n1, df%n2, df%col_names, df%x
end subroutine write_stream

subroutine read_stream(df, iu)
type(data_frame(:, :)), intent(out), allocatable :: df
integer, intent(in) :: iu
integer :: n1, n2
read (iu) n1, n2
allocate (data_frame(n1, n2) :: df)
read (iu) df%col_names, df%x
end subroutine read_stream
end module xpdt_stream_alloc_dummy_mod

program xpdt_stream_alloc_dummy
use xpdt_stream_alloc_dummy_mod, only: data_frame, write_stream, read_stream
implicit none
type(data_frame(:, :)), allocatable :: df_in, df_out
integer :: iu = 10
allocate (data_frame(2, 2) :: df_in)
df_in%col_names = ["x1", "x2"]
df_in%x = reshape([1.0, 2.0, 3.0, 4.0], [2, 2])
open (unit=iu, file="xpdt_stream_alloc_dummy.bin", form="unformatted", access="stream")
call write_stream(df_in, iu)
rewind (iu)
call read_stream(df_out, iu)
close (iu, status="delete")
print *, df_out%n1, df_out%n2
print *, all(df_in%x == df_out%x), all(df_in%col_names == df_out%col_names)
print *, df_out%x
end program xpdt_stream_alloc_dummy
