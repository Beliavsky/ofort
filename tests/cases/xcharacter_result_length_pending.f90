program xcharacter_result_length_pending
implicit none
character(len=:), allocatable :: s
character(len=7) :: fixed

! Expected output: every logical value is T.
print *, len(twice('a')) == 2, len(twice('abcd')) == 8
print *, twice('ab') == 'abab', twice('xyz') == 'xyzxyz'
s = twice('abc')
print *, len(s) == 6, s == 'abcabc'
s = bracket('xy  ')
print *, len(s) == 4, s == '[xy]'
fixed = twice('ab')
print *, fixed == 'abab   '
fixed = twice('abcd')
print *, fixed == 'abcdabc'
print *, twice('a') // bracket('bc ') == 'aa[bc]'

contains

function twice(text) result(value)
character(len=*), intent(in) :: text
character(len=2*len(text)) :: value
value = text // text
end function twice

function bracket(text) result(value)
character(len=*), intent(in) :: text
character(len=:), allocatable :: value
value = '[' // trim(text) // ']'
end function bracket

end program xcharacter_result_length_pending
