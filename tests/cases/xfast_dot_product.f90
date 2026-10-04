integer, parameter :: dp = kind(1.0d0)
real(dp) :: g(4), d(4)
g = [0.25_dp, -0.5_dp, 0.75_dp, -1.0_dp]
d = [-0.1749252_dp, 0.05972976_dp, -0.1656963_dp, 0.08505307_dp]
print *, sum(g*d), dot_product(g,d)
end
