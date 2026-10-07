program xpolymorphic_source_mold_pending
implicit none
type :: base
   integer :: id = -1
end type base
type, extends(base) :: child
   integer, allocatable :: values(:)
end type child
type(child) :: original
class(base), allocatable :: source, copied, molded

original%id = 42
original%values = [10, 20, 30]
allocate(source, source=original)
allocate(copied, source=source)
select type (copied)
type is (child)
   print *, copied%id == 42, all(copied%values == [10, 20, 30])
   copied%values(1) = 99
class default
   print *, .false., .false.
end select
select type (source)
type is (child)
   print *, all(source%values == [10, 20, 30])
class default
   print *, .false.
end select
print *, all(original%values == [10, 20, 30])

allocate(molded, mold=source)
select type (molded)
type is (child)
   print *, molded%id == -1, .not. allocated(molded%values)
   molded%values = [7, 8]
   print *, all(molded%values == [7, 8])
class default
   print *, .false., .false.
   print *, .false.
end select
deallocate(source)
select type (copied)
type is (child)
   print *, all(copied%values == [99, 20, 30])
class default
   print *, .false.
end select
end program xpolymorphic_source_mold_pending
