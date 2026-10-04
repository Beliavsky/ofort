program xinternal_write_component
implicit none
type :: t
  character(len=8) :: text
end type
type(t) :: item
write(unit=item%text, fmt="('x',i2.2)") 7
print *, trim(item%text)
end program xinternal_write_component
