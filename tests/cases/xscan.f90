program xscan
implicit none

integer, parameter :: n = 6

integer :: i
character(len=20) :: s(n)
character(len=5) :: set

s = [character(len=20) :: &
     "abc123", &
     "no digits", &
     "  leading", &
     "hello, world", &
     "ABCdef", &
     ""]

set = "01234"

print *, "scan(string, set) returns the position of the first character"
print *, "in string that is also in set. It returns 0 if none is found."
print *

do i = 1, n
   print *, "string = [", trim(s(i)), "] scan(s,set) =", scan(s(i), set)
end do

print *
print *, "different sets:"
print *, "scan('abc123', '0123456789') =", scan("abc123", "0123456789")
print *, "scan('abc123', 'abc')        =", scan("abc123", "abc")
print *, "scan('abc123', 'xyz')        =", scan("abc123", "xyz")
print *

print *, "back=.true. searches from the right:"
print *, "scan('abc123abc', 'abc')              =", scan("abc123abc", "abc")
print *, "scan('abc123abc', 'abc', back=.true.) =", scan("abc123abc", "abc", back=.true.)
print *

print *, "blank is just another character in set:"
print *, "scan('no digits', ' ') =", scan("no digits", " ")
print *

print *, "case-sensitive examples:"
print *, "scan('ABCdef', 'abc') =", scan("ABCdef", "abc")
print *, "scan('ABCdef', 'ABC') =", scan("ABCdef", "ABC")

end program xscan
