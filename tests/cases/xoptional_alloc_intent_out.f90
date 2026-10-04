program xoptional_alloc_intent_out
implicit none
integer, allocatable :: a(:)

allocate(a(2))
a = [10, 20]
call reset_alloc(a)
print *, allocated(a), size(a), a
call reset_alloc()
print *, "omitted ok"

contains

subroutine reset_alloc(x)
integer, allocatable, intent(out), optional :: x(:)
if (present(x)) then
   allocate(x(3))
   x = [1, 2, 3]
end if
end subroutine reset_alloc

end program xoptional_alloc_intent_out
