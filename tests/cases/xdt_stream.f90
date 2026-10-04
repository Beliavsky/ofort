module xdt_stream_mod
implicit none
integer, parameter :: nlen = 10
type :: data_frame
   character(len=nlen), allocatable :: col_names(:)
   real, allocatable :: x(:,:)
end type data_frame
contains
subroutine write_stream(df, iu)
type(data_frame), intent(in) :: df
integer, intent(in) :: iu
write (iu) shape(df%x), df%col_names, df%x
end subroutine write_stream
subroutine read_stream(df, iu)
type(data_frame), intent(out) :: df
integer, intent(in) :: iu
integer :: n1, n2
read (iu) n1, n2
call alloc(df, n1, n2)
read (iu) df%col_names, df%x
end subroutine read_stream
pure subroutine alloc(df, n1, n2)
type(data_frame), intent(out) :: df
integer, intent(in) :: n1, n2
allocate (df%x(n1,n2), df%col_names(n2))
end subroutine alloc
end module xdt_stream_mod

program xdt_stream
use xdt_stream_mod, only: data_frame, alloc, write_stream, read_stream
implicit none
integer, parameter :: n1 = 3, n2 = 2
type(data_frame) :: df_in, df_out
integer :: iu = 10
call alloc(df_in, n1, n2)
df_in%col_names = ["x1", "x2"]
df_in%x = reshape([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], shape(df_in%x))
open (unit=iu, file="xdt_stream.bin", form="unformatted", access="stream")
call write_stream(df_in, iu)
rewind (iu)
call read_stream(df_out, iu)
print *, all(df_in%x == df_out%x), all(df_in%col_names == df_out%col_names)
end program xdt_stream
