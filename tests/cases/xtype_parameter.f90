program x
  implicit none
  integer, parameter :: dp = kind(1.0d0)

  type body
     real(kind=dp) :: mass
  end type body

  type(body), parameter :: sun = body(1.0d0)

  print *, sun%mass
end program x
