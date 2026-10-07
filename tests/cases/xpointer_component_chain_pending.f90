program xpointer_component_chain_pending
implicit none
type :: holder
   integer, pointer :: values(:) => null()
end type holder
type(holder) :: first, second
integer, target :: a(8)
a = [1, 2, 3, 4, 5, 6, 7, 8]
first%values(0:) => a(1:7:2)
second%values(-1:) => first%values(3:1:-1)
second%values(0) = 500
print *, a
a(3) = 300
print *, second%values
second%values = [70, 50, 30]
print *, a
print *, first%values
end program xpointer_component_chain_pending
