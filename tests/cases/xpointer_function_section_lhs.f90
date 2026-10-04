program xpointer_function_section_lhs
implicit none
integer, target :: a(5)

a = [10, 20, 30, 40, 50]
getp() = [200, 300, 400]
print *, a

contains

function getp() result(p)
integer, pointer :: p(:)
p => a(2:4)
end function getp

end program xpointer_function_section_lhs
