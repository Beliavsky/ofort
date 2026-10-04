program data_initialization_once
implicit none
call probe()
call probe()
print *, next_value()
print *, next_value()
contains
subroutine probe()
logical :: first
integer :: count, a(2)
save first
data first /.true./
data count /0/
data a(1) /10/
data a(2) /20/
count = count + 1
print *, first, count, a
first = .false.
a = a + 1
end subroutine
integer function next_value()
integer :: count
data count /0/
count = count + 1
next_value = count
end function
end program
