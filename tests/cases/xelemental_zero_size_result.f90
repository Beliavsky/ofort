module m
implicit none
type :: frame
   integer :: n = 0
end type frame
contains
elemental function num_var(df) result(nvar)
type(frame), intent(in) :: df
integer :: nvar
nvar = df%n
end function num_var
function common_value(ivec, idef) result(jj)
integer, intent(in) :: ivec(:)
integer, intent(in), optional :: idef
integer :: jj
if (size(ivec) == 0) then
   jj = 0
else if (minval(ivec) == maxval(ivec)) then
   jj = minval(ivec)
else if (present(idef)) then
   jj = idef
else
   jj = 0
end if
end function common_value
end module m

program main
use m
implicit none
type(frame) :: df(0)
print *, common_value(num_var(df))
end program main
