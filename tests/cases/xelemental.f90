module cylinder_mod
use, intrinsic :: iso_fortran_env, only: real64
implicit none

integer, parameter :: dp = kind(1.0d0)

contains

pure elemental real(kind=dp) function cylinder_volume(radius, height) result(volume)
! Return the volume of a cylinder.
real(kind=dp), intent(in) :: radius
real(kind=dp), intent(in) :: height

real(kind=dp), parameter :: pi = acos(-1.0_dp)

volume = pi * radius**2 * height

end function cylinder_volume

elemental subroutine cylinder_volume_area(radius, height, volume, surface_area)
! Return the volume and surface area of a cylinder.
real(kind=dp), intent(in) :: radius
real(kind=dp), intent(in) :: height
real(kind=dp), intent(out) :: volume
real(kind=dp), intent(out) :: surface_area

real(kind=dp), parameter :: pi = acos(-1.0_dp)

volume = pi * radius**2 * height
surface_area = 2.0_dp * pi * radius * (radius + height)

end subroutine cylinder_volume_area

end module cylinder_mod

program test_cylinder_volume
use cylinder_mod, only: dp, cylinder_volume, cylinder_volume_area
implicit none

integer, parameter :: n = 4

real(kind=dp) :: radius_scalar
real(kind=dp) :: height_scalar
real(kind=dp) :: volume_scalar
real(kind=dp) :: area_scalar
real(kind=dp) :: radius_array(n)
real(kind=dp) :: height_array(n)
real(kind=dp) :: volume_array(n)
real(kind=dp) :: area_array(n)

radius_scalar = 2.0_dp
height_scalar = 5.0_dp

volume_scalar = cylinder_volume(radius_scalar, height_scalar)

print *, "scalar function test:"
print *, "radius =", radius_scalar
print *, "height =", height_scalar
print *, "volume =", volume_scalar

call cylinder_volume_area(radius_scalar, height_scalar, volume_scalar, area_scalar)

print *
print *, "scalar subroutine test:"
print *, "radius       =", radius_scalar
print *, "height       =", height_scalar
print *, "volume       =", volume_scalar
print *, "surface area =", area_scalar

radius_array = [1.0_dp, 2.0_dp, 3.0_dp, 4.0_dp]
height_array = [10.0_dp, 5.0_dp, 2.0_dp, 1.0_dp]

volume_array = cylinder_volume(radius_array, height_array)

print *
print *, "array function test:"
print *, "radii   =", radius_array
print *, "heights =", height_array
print *, "volumes =", volume_array

call cylinder_volume_area(radius_array, height_array, volume_array, area_array)

print *
print *, "array subroutine test:"
print *, "radii         =", radius_array
print *, "heights       =", height_array
print *, "volumes       =", volume_array
print *, "surface areas =", area_array

call cylinder_volume_area(radius_array, 2.0_dp, volume_array, area_array)

print *
print *, "array radius with scalar height:"
print *, "radii         =", radius_array
print *, "height        =", 2.0_dp
print *, "volumes       =", volume_array
print *, "surface areas =", area_array

end program test_cylinder_volume
