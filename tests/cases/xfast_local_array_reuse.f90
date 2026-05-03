program xfast_local_array_reuse
  implicit none
  integer :: i, y
  do i = 1, 3
     call f(i, y)
     print *, y
  end do
contains
  subroutine f(i, y)
    integer, intent(in) :: i
    integer, intent(out) :: y
    real(kind=8) :: scratch(4)
    scratch(1) = i
    y = int(scratch(1) + scratch(2))
  end subroutine f
end program xfast_local_array_reuse
