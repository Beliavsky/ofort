program xrank_attribute_dummy
implicit none
real :: a(2,3)
real :: v(4)
a = 1.0
v = [1.0, 2.0, 3.0, 4.0]
call s(a)
call t(v)
contains
  subroutine s(x)
    real, rank(2), intent(in) :: x
    print *, rank(x), shape(x)
  end subroutine s
  subroutine t(x)
    real, rank(1), intent(in) :: x
    print *, rank(x), size(x)
  end subroutine t
end program xrank_attribute_dummy
