program xselected_logical_kind
implicit none
integer :: k1, k8, k33
logical(kind=selected_logical_kind(1)) :: l1
logical(kind=selected_logical_kind(8)) :: l8

k1 = selected_logical_kind(1)
k8 = selected_logical_kind(8)
k33 = selected_logical_kind(33)
l1 = .true.
l8 = .false.
print *, k1, k8, k33
print *, kind(l1), kind(l8), l1, l8
end program xselected_logical_kind
