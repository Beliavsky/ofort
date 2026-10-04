implicit none
character(len=100) :: s1, s2
logical :: tf
integer :: iu

open(newunit=iu, file="xread_param_record.tmp", action="write", status="replace")
write(iu, '(a)') 'etf_cef_quotes.csv spy.csv pdi.csv vxx_tvix_spy.csv tvix_spy.csv ! file with prices or returns'
write(iu, '(a)') 'F ! read_returns -- (true,false) read (returns,prices)'
write(iu, '(a)') '"yyyy-mm-dd" ! date_format -- should be "yyyy-mm-dd"'
close(iu)

open(newunit=iu, file="xread_param_record.tmp", action="read", status="old")
read(iu, *) s1
read(iu, *) tf
read(iu, *) s2
close(iu, status="delete")

print "('s1 = ',a,' tf = ',l1,' s2 = ',a)", trim(s1), tf, trim(s2)
end
