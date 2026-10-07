program xcharacter_overlap_assignment_pending
implicit none
character(len=8) :: s
character(len=4) :: words(4)

! Expected output: every logical value is T.
! The right-hand side must be evaluated before overlapping storage changes.
s = 'abcdefgh'
s(2:8) = s(1:7)
print *, s == 'aabcdefg'
s = 'abcdefgh'
s(1:7) = s(2:8)
print *, s == 'bcdefghh'

words = ['aaaa', 'bbbb', 'cccc', 'dddd']
words(2:4) = words(1:3)
print *, all(words == ['aaaa', 'aaaa', 'bbbb', 'cccc'])
words = ['aaaa', 'bbbb', 'cccc', 'dddd']
words(1:3) = words(2:4)
print *, all(words == ['bbbb', 'cccc', 'dddd', 'dddd'])

words = ['abcd', 'efgh', 'ijkl', 'mnop']
words(:)(2:4) = words(:)(1:3)
print *, all(words == ['aabc', 'eefg', 'iijk', 'mmno'])
end program xcharacter_overlap_assignment_pending
