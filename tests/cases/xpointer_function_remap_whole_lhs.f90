program xpointer_function_remap_whole_lhs
implicit none
integer, target :: a(5)

a = [10, 20, 30, 40, 50]
getp() = [200, 300, 400]
print *, a
print *, lbound(getp()), ubound(getp())

contains

function getp() result(p)
integer, pointer :: p(:)
p(0:) => a(2:4)
end function getp

end program xpointer_function_remap_whole_lhs
