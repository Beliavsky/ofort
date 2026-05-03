program xcharacter_len_expr
implicit none
character(len=5) :: input
character(len=len(input)) :: same
character(len=max(1, len(input) + 2)) :: longer
character, parameter :: tag*3 = "abc"
input = "hello"
print *, len(longer)
same = input
longer = input
print *, len(input), len(same), len(longer), len(tag)
print *, trim(same), trim(tag)
end program xcharacter_len_expr
