program xpointer_function_lhs
implicit none
integer, target :: t

t = 10
getp() = 42
print *, t

contains

function getp() result(p)
integer, pointer :: p
p => t
end function getp

end program xpointer_function_lhs
