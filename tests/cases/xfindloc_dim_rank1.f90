program main
  character(len=4) :: words(3)
  integer :: i
  words = [character(len=4) :: "aa", "bb", "cc"]
  i = findloc(words, "bb", dim=1)
  print *, i
  print *, maxloc([3, 7, 5], dim=1), minloc([3, 7, 5], dim=1)
end program main
