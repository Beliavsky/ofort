module dup_elem_a
contains
  pure elemental function uppercase(s) result(out)
    character(len=*), intent(in) :: s
    character(len=len(s)) :: out
    integer :: i, code
    out = s
    do i = 1, len(s)
      code = iachar(out(i:i))
      if (code >= iachar('a') .and. code <= iachar('z')) out(i:i) = achar(code - 32)
    end do
  end function uppercase
end module dup_elem_a

module dup_elem_b
contains
  function uppercase(s) result(out)
    character(len=*), intent(in) :: s
    character(len=len(s)) :: out
    out = s
  end function uppercase
end module dup_elem_b

program main
  use dup_elem_a, only: uppercase
  character(len=4) :: words(2)
  character(len=4) :: up(2)
  words = [character(len=4) :: "ab", "cd"]
  up = uppercase(words)
  print *, trim(up(1)), trim(up(2))
end program main
