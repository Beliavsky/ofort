program test_allocatable_scalars
implicit none

integer, parameter :: dp = kind(1.0d0)

integer, allocatable :: i
real(kind=dp), allocatable :: x

! Allocate scalar variables.
allocate(i)
allocate(x)

i = 42
x = 3.141592653589793_dp

print *, "after allocation and assignment:"
print *, "allocated(i) = ", allocated(i), ", i = ", i
print *, "allocated(x) = ", allocated(x), ", x = ", x

! Allocatable scalars can also be deallocated.
deallocate(i)
deallocate(x)

print *
print *, "after deallocation:"
print *, "allocated(i) = ", allocated(i)
print *, "allocated(x) = ", allocated(x)

end program test_allocatable_scalars
