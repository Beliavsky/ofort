program xalloc_component_intent_out
implicit none

type box
   integer, allocatable :: a(:)
end type box

type(box) :: b

allocate(b%a(2))
b%a = [10, 20]
call reset_alloc(b%a)
print *, allocated(b%a), size(b%a), b%a

contains

subroutine reset_alloc(x)
integer, allocatable, intent(out) :: x(:)
allocate(x(3))
x = [1, 2, 3]
end subroutine reset_alloc

end program xalloc_component_intent_out
