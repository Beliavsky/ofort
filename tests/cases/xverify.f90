program xverify
implicit none

integer, parameter :: n = 6

integer :: i
character(len=20) :: s(n)

s = [character(len=20) :: &
     "abc123", &
     "abcdef", &
     "12345", &
     "abc def", &
     "ABCdef", &
     ""]

print *, "verify(string, set) returns the position of the first character"
print *, "in string that is not in set. It returns 0 if all characters are in set."
print *

do i = 1, n
   print *, "string = [", trim(s(i)), "]"
   print *, "  verify(s, 'abcdefghijklmnopqrstuvwxyz') =", &
            verify(s(i), "abcdefghijklmnopqrstuvwxyz")
   print *, "  verify(s, '0123456789') =", &
            verify(s(i), "0123456789")
end do

print *
print *, "direct examples:"
print *, "verify('abc123', 'abcdefghijklmnopqrstuvwxyz') =", &
         verify("abc123", "abcdefghijklmnopqrstuvwxyz")
print *, "verify('abcdef', 'abcdefghijklmnopqrstuvwxyz') =", &
         verify("abcdef", "abcdefghijklmnopqrstuvwxyz")
print *, "verify('12345',  '0123456789') =", &
         verify("12345", "0123456789")
print *, "verify('abc def', 'abcdefghijklmnopqrstuvwxyz') =", &
         verify("abc def", "abcdefghijklmnopqrstuvwxyz")
print *

print *, "back=.true. searches from the right:"
print *, "verify('abc123abc', 'abc')              =", &
         verify("abc123abc", "abc")
print *, "verify('abc123abc', 'abc', back=.true.) =", &
         verify("abc123abc", "abc", back=.true.)
print *

print *, "case-sensitive examples:"
print *, "verify('ABCdef', 'abcdef') =", verify("ABCdef", "abcdef")
print *, "verify('ABCdef', 'ABCdef') =", verify("ABCdef", "ABCdef")

end program xverify
