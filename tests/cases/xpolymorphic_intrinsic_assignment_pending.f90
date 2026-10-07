program xpolymorphic_intrinsic_assignment_pending
implicit none
integer, parameter :: dp = kind(1.0d0)
class(*), allocatable :: x, y

x = 17
select type (x)
type is (integer)
   print *, x == 17
class default
   print *, .false.
end select

x = "Fortran"
y = x
x = "F"
select type (x)
type is (character(len=*))
   print *, len(x) == 1, x == "F"
class default
   print *, .false., .false.
end select
select type (y)
type is (character(len=*))
   print *, len(y) == 7, y == "Fortran"
class default
   print *, .false., .false.
end select

x = 2.5_dp
select type (x)
type is (real(kind=dp))
   print *, kind(x) == dp, x == 2.5_dp
class default
   print *, .false., .false.
end select
y = x
select type (y)
type is (real(kind=dp))
   print *, y == 2.5_dp
class default
   print *, .false.
end select

y = "a longer string"
x = y
select type (x)
type is (character(len=*))
   print *, len(x) == len("a longer string"), x == "a longer string"
class default
   print *, .false., .false.
end select
end program xpolymorphic_intrinsic_assignment_pending
