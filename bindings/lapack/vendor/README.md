These fixed-form sources are from Reference LAPACK 3.12.1:

https://github.com/Reference-LAPACK/lapack/tree/v3.12.1

SRC: zgesv, zgetrf, zgetrf2, zgetrs, zlaswp.
BLAS/SRC: zgemm, ztrsm, zscal, zswap, izamax.

They supplement the local real-double-precision lapack_d.f90 for the optional
native backend. Existing real utilities (LSAME, XERBLA, DLAMCH, ILAENV) come
from that bundled source. Installed-library builds do not compile these files.

The upstream license is retained in LICENSE. The original source headers are
retained. These files are compiled; ofort does not parse them at runtime.
