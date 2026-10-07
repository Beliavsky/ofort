program xcharacter_deferred_assignment_pending
implicit none
character(len=:), allocatable :: s, words(:)

! Expected output: every logical value is T.
s = 'abc'
print *, allocated(s), len(s) == 3, s == 'abc'
s = s // 'de'
print *, len(s) == 5, s == 'abcde'
s = 'x'
print *, len(s) == 1, s == 'x'

words = [character(len=4) :: 'a', 'bc']
print *, allocated(words), len(words) == 4, size(words) == 2
words = [character(len=6) :: 'long', 'x', 'yz']
print *, len(words) == 6, size(words) == 3
print *, all(words == [character(len=6) :: 'long', 'x', 'yz'])

! A section assignment must not reallocate the array or its character length.
words(:) = [character(len=8) :: '12345678', 'abcdefgh', 'uvwxyz12']
print *, len(words) == 6, size(words) == 3
print *, all(words == ['123456', 'abcdef', 'uvwxyz'])
end program xcharacter_deferred_assignment_pending
