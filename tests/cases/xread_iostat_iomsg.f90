program xread_iostat_iomsg
implicit none
integer :: values(2), stat
character(len=80) :: msg

values = -99
msg = ""
read ("11", *, iostat=stat, iomsg=msg) values
print *, stat, trim(msg), values

values = -99
msg = ""
read ("dog cat", *, iostat=stat, iomsg=msg) values
print *, stat, trim(msg), values

end program xread_iostat_iomsg
