program xformat_at
implicit none
character(len=8) :: s
s = "abc"
print "(a,a,a)", "<", s, ">"
print "(a,at,a)", "<", s, ">"
print "(a,2at,a)", "<", s, s, ">"
end program xformat_at
