complex(4) :: z4
complex(8) :: z8
complex(kind=16) :: z16
complex(8) :: a(2,2)
z4 = (1.0, 2.0)
z8 = (3.0, 4.0)
z16 = (5.0, 6.0)
a = z8
print *, kind(z4), kind(z8), kind(z16), kind(a(1,1))
