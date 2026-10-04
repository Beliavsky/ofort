program count_pack
implicit none
integer :: v(3) = [1,-4,9]
print*,pack(v,v>0)
print*,count(v>0)
print*,size(v)
print*,sum(v)
print*,sum(v,v>0)
print*,sum(pack(v,v>0))
print*,product(v,v>0)
print*,product(v,mask=v>0)
end program count_pack
