program ximport_f2023_pending
implicit none
integer, parameter :: dp = kind(1.0d0)
interface
  subroutine s_only(x)
    import, only: dp
    real(kind=dp), intent(in) :: x
  end subroutine s_only
  subroutine s_none(x)
    import, none
    real, intent(in) :: x
  end subroutine s_none
  subroutine s_all(x)
    import, all
    real(kind=dp), intent(in) :: x
  end subroutine s_all
end interface
print *, dp
end program ximport_f2023_pending
