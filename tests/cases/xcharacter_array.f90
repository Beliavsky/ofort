program character_array
implicit none
character (len=:), allocatable :: s1(:),s2(:),s3(:),s4(:)
integer :: i
s1 = ["one ","two ","five"]
s2 = [character (len=4) :: "one","two","five"]
print*,s1 == s2
print "(*(a,:,1x))",("'" // trim(s1(i)) // "'", i=1,size(s1))
s3 = ["1","2","3"]
s4 = [s2,[character (len=len(s2)) :: s3]]
print "(*(a,:,1x))",("'" // trim(s4(i)) // "'", i=1,size(s4))
end program character_array
