module func_pointer_mod
use iso_c_binding, only: c_int, c_funptr, c_funloc, c_f_procpointer
implicit none

abstract interface
   function func_2i(i, j) result(res) bind(c)
      import c_int
      integer(c_int), value, intent(in) :: i, j
      integer(c_int)                    :: res
   end function func_2i
end interface

contains

function cfunc_2i(i, j, func_ptr) result(res) bind(c)
integer(c_int), value, intent(in) :: i, j
type(c_funptr), value, intent(in)  :: func_ptr
integer(c_int)                    :: res
procedure(func_2i), pointer        :: fptr

call c_f_procpointer(func_ptr, fptr)
res = fptr(i, j)
end function cfunc_2i

function sum_int(i,j) result(res) bind(c)
integer(c_int), intent(in), value :: i, j
integer(c_int)                    :: res
res = i + j
end function sum_int

function diff_int(i,j) result(res) bind(c)
integer(c_int), intent(in), value :: i, j
integer(c_int)                    :: res
res = i - j
end function diff_int

end module func_pointer_mod

program test_func_pointer
use iso_c_binding   , only: c_int, c_funloc
use func_pointer_mod, only: sum_int, diff_int, cfunc_2i
implicit none

print*, cfunc_2i(3_c_int, 2_c_int, c_funloc(sum_int))
print*, cfunc_2i(3_c_int, 2_c_int, c_funloc(diff_int))
end program test_func_pointer
