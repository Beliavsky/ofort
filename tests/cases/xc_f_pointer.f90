module c_alloc_squares_mod
use iso_c_binding, only : c_ptr, c_f_pointer, c_int, c_size_t, c_sizeof, c_null_ptr
implicit none

interface
   function c_malloc(size) bind(c, name="malloc")
      import c_ptr, c_size_t
      integer(c_size_t), value :: size
      type(c_ptr)              :: c_malloc
   end function c_malloc

   subroutine c_free(ptr) bind(c, name="free")
      import c_ptr
      type(c_ptr), value :: ptr
   end subroutine c_free
end interface

contains

function squares_p(sq_max, nsq) result(c_p) bind(c)
integer(c_int), value, intent(in)  :: sq_max
integer(c_int), intent(out)        :: nsq
type(c_ptr)                        :: c_p
integer(c_int), pointer            :: f_ip(:)
integer(c_int)                     :: i, n
integer(c_size_t)                  :: nbytes

nsq = 0_c_int
do i = 1_c_int, sq_max
   if (i*i <= sq_max) nsq = nsq + 1_c_int
end do

if (nsq <= 0_c_int) then
   c_p = c_null_ptr
   return
end if

nbytes = int(nsq, kind=c_size_t) * c_sizeof(0_c_int)
c_p = c_malloc(nbytes)

call c_f_pointer(c_p, f_ip, [nsq])

do n = 1_c_int, nsq
   f_ip(n) = n*n
end do

nullify(f_ip)
end function squares_p

end module c_alloc_squares_mod

program x_c_f_pointer
use iso_c_binding, only : c_ptr, c_f_pointer, c_int
use c_alloc_squares_mod, only : squares_p, c_free
implicit none

type(c_ptr) :: c_p
integer(c_int), pointer :: f_ip(:) => null()
integer(c_int) :: nsq
integer :: sq_max

print "(*(a6))", "sq_max", "#sq", "f_ip"

do sq_max = 1, 41, 20
   c_p = squares_p(int(sq_max, kind=c_int), nsq)
   call c_f_pointer(c_p, f_ip, [nsq])
   print "(*(i6))", sq_max, nsq, f_ip
   nullify(f_ip)
   call c_free(c_p)
end do
end program x_c_f_pointer
