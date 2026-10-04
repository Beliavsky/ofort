program xstring_elemental
implicit none
character(len=*), parameter :: num = "0123456789"

print *, scan(["2022-Jan", "abcdefgh"], num)
print *, verify(string=["13579", "18Dec"], set=num)
print *, index(num, substring=["34", "35"])
print *, len_trim(["abc ", " abc"])
print "(*(:,'''',a,''' '))", adjustl(" abc"), adjustr("abc ")

end program xstring_elemental
