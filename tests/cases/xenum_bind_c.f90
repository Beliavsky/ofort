program xenum_bind_c
implicit none
enum, bind(c)
  enumerator :: red = 1, green, blue = 10, yellow
end enum
print *, red, green, blue, yellow
end program xenum_bind_c
