program xoptional_pointer_intent_out
implicit none
integer, target :: t
integer, pointer :: p

t = 10
p => t
call reset_pointer(p)
print *, associated(p)
call reset_pointer()
print *, "omitted ok"

contains

subroutine reset_pointer(x)
integer, pointer, intent(out), optional :: x
if (present(x)) then
   x => null()
end if
end subroutine reset_pointer

end program xoptional_pointer_intent_out
