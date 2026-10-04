implicit none
character(len=*), parameter :: fmt = "(a,1x,i0,1x)"
write (*,fmt,advance="no") "i =", 1
write (*,fmt,advance="no") "i =", 2
write (*,*)
end
