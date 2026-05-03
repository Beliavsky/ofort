integer :: i, j
write (*,"(*(i0,1x))") ((i, j, i+j, i=2,4), j=5,8)
end
