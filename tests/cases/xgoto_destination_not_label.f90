program goto_destination_not_label
implicit none
integer :: i
i=0
go to 40
30 i=-100
40 i=i+1
if (i<3) go to 40
50 go to 60
i=-200
60 print *, i
end program
