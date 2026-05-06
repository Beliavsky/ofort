module xkeyword_type_mod
  type data
    integer :: i
  end type
end module
use xkeyword_type_mod
type(data) :: dat
dat%i = 7
if (dat%i /= 7) print *, 101
print *, 'pass'
end
