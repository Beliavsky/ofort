program xpointer_function_component_target_lhs
implicit none

type box
   integer, pointer :: p
end type box

type(box) :: b
integer, target :: t

t = 42
b%p => t
getp() = 99
print *, t

contains

function getp() result(p)
integer, pointer :: p
p => b%p
end function getp

end program xpointer_function_component_target_lhs
