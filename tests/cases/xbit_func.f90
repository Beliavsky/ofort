program bit_functions
implicit none
integer, parameter :: ikind = selected_int_kind(1)
integer(kind=ikind) :: i, j, nbits
integer(kind=ikind), allocatable :: ivec(:)
integer, parameter :: ni = 4
logical, allocatable :: bits(:)
nbits = bit_size(i)
allocate(bits(nbits))
ivec = [(i, i=nbits-1, 0, -1)]
print "('bit representation of ',i0,'-bit integers')", nbits
print "(14x,'bit position')"
print "(9x,'i',2x,*(i3))", ivec
do i = -2, ni
   print "(i10,2x,*(i3))", i, merge(1, 0, btest(i, ivec))
end do
print "(/,a,*(1x,i0))", &
  "not(1), iand(2,3), ior(2,3), ieor(2,3) =", &
   not(1), iand(2,3), ior(2,3), ieor(2,3)
end program bit_functions
