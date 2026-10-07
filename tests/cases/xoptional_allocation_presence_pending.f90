program xoptional_allocation_presence_pending
implicit none
integer, allocatable :: a(:), scalar
call accept_allocatable(a)
print *, inspect(x=a)
allocate(a(0))
call accept_allocatable(a)
print *, inspect(x=a)
deallocate(a)
allocate(a(2))
a = [1, 2]
print *, inspect(x=a)
print *, inspect_scalar(x=scalar)
allocate(scalar)
scalar = 7
print *, inspect_scalar(x=scalar)
contains
subroutine accept_allocatable(x)
integer, allocatable, optional, intent(in) :: x(:)
print *, present(x), allocated(x)
end subroutine accept_allocatable
integer function inspect(x) result(value)
integer, optional, intent(in) :: x(:)
value = -1
if (present(x)) value = sum(x)
end function inspect
integer function inspect_scalar(x) result(value)
integer, optional, intent(in) :: x
value = -1
if (present(x)) value = x
end function inspect_scalar
end program xoptional_allocation_presence_pending
