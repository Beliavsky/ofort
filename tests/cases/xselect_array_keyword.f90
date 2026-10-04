program test_select_array_keyword
implicit none
logical :: select(3)
integer :: k
select = .true.
do k = 1, 3
    SELECT( K ) = .FALSE.
end do
select(2) = .true.
select case (count(select))
case (1)
    print *, select
case default
    stop 1
end select
end program test_select_array_keyword
