implicit none
integer :: i, j, ij
ido: do i=1,5
   jdo: do j=1,3
      ij = i*j
      print "(*(i4))", i,j,ij
      if (ij > 10) exit jdo
   end do jdo
   if (ij > 20) exit ido
end do ido
end
