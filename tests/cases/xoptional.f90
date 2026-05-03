module optional_mod
implicit none

contains

real function scale_value(x, factor)
real, intent(in) :: x
real, intent(in), optional :: factor

if (present(factor)) then
   scale_value = x * factor
else
   scale_value = x
end if

end function scale_value

subroutine print_value(x, label)
real, intent(in) :: x
character(len=*), intent(in), optional :: label

if (present(label)) then
   print *, label, x
else
   print *, x
end if

end subroutine print_value

subroutine wrapper(x, factor)
real, intent(in) :: x
real, intent(in), optional :: factor

print *, scale_value(x, factor)

end subroutine wrapper

end module optional_mod

program xoptional
use optional_mod, only: scale_value, print_value, wrapper
implicit none

print *, scale_value(10.0)
print *, scale_value(10.0, 2.0)

call print_value(5.0)
call print_value(5.0, "x = ")

call wrapper(7.0)
call wrapper(7.0, 3.0)

end program xoptional
