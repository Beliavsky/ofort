# ofort Extension Modules

`ofort` includes a small set of nonstandard extension modules for interpreted
workflows. They are convenience modules, not part of the core Fortran language
support required to run ordinary `ofort` programs.

Programs must import these procedures explicitly:

```fortran
use ofort_random_mod, only: rnorm
```

These modules are implemented by the `ofort` runtime. Programs that use them
are intended for `ofort` unless a compatible Fortran implementation of the same
module API is also provided for compiled builds.

## Module Summary

| Module | Purpose | Procedures |
| --- | --- | --- |
| `ofort_lapack_mod` | optional compiled LAPACK interface | `dgesv`, `dgetrf`, `dgetri`, `dpotrf`, `dsyev`, `dgeev`, `dgeqrf`, `dorgqr`, `dgesvd`, `zgesv` |
| `ofort_random_mod` | random variates | `rnorm`, `rnorm_fill`, `randn`, `normrnd`, `unifrnd`, `exprnd`, `lognrnd`, `gamrnd`, `poissrnd`, `binornd`, `trnd`, `laprnd`, `sechrnd`, `logisticrnd` |
| `ofort_la_mod` | small dense linear algebra helpers | `matmul2`, `transpose2`, `crossprod`, `tcrossprod`, `center_cols`, `col_sums`, `col_means`, `eye`, `diag`, `det`, `eig`, `svd`, `qr`, `lu`, `pinv`, `cond`, `norm`, `triu`, `tril`, `kron`, `solve`, `mldivide`, `inv`, `rank`, `chol`, `trace`, `outer_product`, `is_square`, `is_diagonal`, `is_symmetric`, `is_invertible` |
| `ofort_io_mod` | simple numeric text readers | `read_matrix`, `read_vector` |
| `ofort_statistics_mod` | vector, matrix, and column statistics | `mean`, `variance`, `sd`, `median`, `moment`, `cov`, `cor`, `variance_given_mean`, `sd_given_mean`, `calc_stats`, `calc_col_stats`, `pca`, `pca_transform`, `pca_inverse_transform` |
| `stdlib_stats` | Fortran stdlib statistics compatibility subset | `mean`, `var`, `median`, `moment`, `cov`, `corr`, `pca`, `pca_transform`, `pca_inverse_transform` |
| `stdlib_linalg` | Fortran stdlib linear-algebra compatibility subset | `eye`, `diag`, `det`, `eig`, `svd`, `qr`, `lu`, `pinv`, `cond`, `norm`, `triu`, `tril`, `kron`, `solve`, `inv`, `rank`, `chol`, `trace`, `outer_product`, `is_square`, `is_diagonal`, `is_symmetric`, `is_invertible` |
| `stdlib_io` | Fortran stdlib text I/O compatibility subset | `loadtxt`, `savetxt` |
| `stdlib_stats_distribution_normal` | Fortran stdlib normal-distribution compatibility subset | `rvs_normal`, `pdf_normal`, `cdf_normal` |

`ofort_stats_mod` is accepted as an alias for `ofort_statistics_mod`.

`stdlib_stats` is a compatibility subset, not a bundled implementation of the
full Fortran stdlib. It lets simple code using stdlib names run in `ofort`.
When compiling the same source with an external Fortran compiler, use the real
Fortran stdlib package.

`stdlib_linalg` follows the same pattern for a small linear-algebra subset.

`stdlib_io` follows the same pattern for simple text matrix loading.

## `ofort_random_mod`

`ofort_random_mod` provides scalar, rank-1, and rank-2 random variates for a
small MATLAB-style distribution subset. Distribution parameters are scalar
numeric values. Optional trailing size arguments select the result shape:

```fortran
z = randn()
x = randn(n)
a = randn(nrow, ncol)

x = normrnd(mu, sigma, n)
a = normrnd(mu, sigma, nrow, ncol)
```

Supported distribution generators:

- `randn([n[, ncol]])`: standard normal.
- `normrnd(mu, sigma[, n[, ncol]])`: normal with mean `mu` and standard
  deviation `sigma`.
- `unifrnd(a, b[, n[, ncol]])`: continuous uniform on `[a,b)`.
- `exprnd(mu[, n[, ncol]])`: exponential with mean `mu`.
- `lognrnd(mu, sigma[, n[, ncol]])`: lognormal.
- `gamrnd(shape, scale[, n[, ncol]])`: gamma.
- `poissrnd(lambda[, n[, ncol]])`: Poisson.
- `binornd(ntrial, p[, n[, ncol]])`: binomial.
- `trnd(nu[, n[, ncol]])`: Student t.
- `laprnd(mu, b[, n[, ncol]])`: Laplace with location `mu` and scale `b`.
- `sechrnd(mu, s[, n[, ncol]])`: hyperbolic secant with location `mu` and
  scale `s`.
- `logisticrnd(mu, s[, n[, ncol]])`: logistic with location `mu` and scale
  `s`.

Invalid distribution parameters return `NaN` for generated values.

### `rnorm`

```fortran
z = rnorm()
z = rnorm(n)
z = rnorm(n, method)
```

Returns standard normal random variates as `double precision`.

Arguments:

- `n`: optional integer number of variates. If omitted, `rnorm` returns a scalar.
  If supplied, `rnorm` returns a rank-1 array of length `n`.
- `method`: optional integer random-normal method. Method `1` is Box-Muller
  trigonometric generation. Method `2` is Marsaglia polar generation. The
  default is `2`.

Examples:

```fortran
double precision :: z
double precision, allocatable :: x(:)

z = rnorm()
x = rnorm(1000)
x = rnorm(1000, 1)
```

### `rnorm_fill`

```fortran
call rnorm_fill(x)
call rnorm_fill(x, method)
```

Fills an existing real scalar or real array with standard normal variates.

Arguments:

- `x`: real scalar or real array output. Rank-1 and rank-2 arrays are supported.
- `method`: optional integer generation method. Method `1` is Box-Muller.
  Method `2` is Marsaglia polar. The default is `2`.

`rnorm_fill` is preferred for large existing arrays because it avoids allocating
a temporary result.

## `ofort_lapack_mod`

This optional module calls compiled LAPACK through a separate C adapter and
an interoperable Fortran bridge. Numerical kernels and their BLAS dependencies
execute in the compiled library. The regular interpreter build requires only
the C compiler; gfortran is needed to build the optional backend.

```fortran
use ofort_lapack_mod, only: dgesv, dsyev, dgesvd
```

The initial subset covers the nine real double precision routines called by
`python_mod`, plus the double complex solver `zgesv`. Names, argument order,
column-major storage, leading dimensions, overwritten arrays, one-based pivot
indices, and `INFO` follow LAPACK. Workspace queries (`lwork=-1`) are supported.
Keyword arguments and USE renaming are supported. Arrays must be allocated
whole arrays or array components, real64/complex(real64) as appropriate;
integer pivot arrays use default INTEGER. Array sections and element-sequence
actuals are not supported by this initial native interface. Dimension and
storage checks occur before a native call. Invalid scalar options/dimensions
return negative `INFO`; short actual arrays produce an interpreter error.

Build the backend from the local bundled `lapack_d.f90`:

```text
make lapack
```

Run the small solve/eigenvalue example with
`ofort --fast bindings/lapack/demo_lapack.f90`, or use
`make -f bindings/lapack/makefile demo` to build and run it.

Or link an installed LP64 LAPACK/BLAS library instead:

```text
make -f bindings/lapack/makefile LAPACK_SOURCE= LAPACK_LIBS="-llapack -lblas"
```

The bundled-source build supplements `lapack_d.f90` with the reference LAPACK
3.12.1 `ZGESV` solver and its required complex BLAS routines under
`bindings/lapack/vendor`, retaining the upstream license. Installed-library
builds use their own complex solver. Add those vendor sources to a compiled
Fortran build only if it calls `zgesv` and the bundled source lacks that routine.

The Windows backend is `ofort_lapack_backend.dll` beside `ofort.exe`. On Linux
and macOS the default backend is `./libofort_lapack_backend.so` or
`./libofort_lapack_backend.dylib`. Set `OFORT_LAPACK_LIBRARY` to an explicit
library path when needed. A missing backend produces an actionable error at
the first call. `--check` validates arguments without loading the library.

Create and run a native-LAPACK copy of the existing `python_mod` driver:

```text
python scripts/prepare_python_lapack.py
ofort --fast --time bindings/lapack/python_native.f90 xpython.f90
```

The preparation script preserves `python.f90` and replaces its local LAPACK
interface blocks with `use ofort_lapack_mod` statements in a generated copy.
Omit `lapack_d.f90` from the interpreter command to avoid parsing it.

For compiled programs the supplied standard Fortran interface module uses
ordinary external LAPACK symbols and can link the same bundled source or an
installed LAPACK library:

```text
gfortran -O3 -Ibindings/lapack bindings/lapack/ofort_lapack_mod.o lapack_d.f90 bindings/lapack/python_native.f90 xpython.f90 -o xpython_native.exe
```

The backend does not replace the existing `ofort_la_mod` algorithms yet.

## `ofort_la_mod`

The linear algebra procedures operate on numeric arrays and return
`double precision` numeric results where applicable.

### `eye`

```fortran
a = eye(n)
a = eye(nrow, ncol)
```

Returns an identity-like `double precision` matrix. The optional `mold`
argument accepted by Fortran stdlib is accepted but does not currently affect
the result type.

### `diag`

```fortran
a = diag(v)
v = diag(a)
v = diag(a, k)
```

For a rank-1 vector, returns a square diagonal matrix. For a rank-2 matrix,
returns the selected diagonal as a rank-1 vector. `k=0` is the main diagonal,
positive `k` selects a superdiagonal, and negative `k` selects a subdiagonal.

### `trace`

```fortran
t = trace(a)
```

Returns the sum of the main diagonal of a rank-2 numeric array.

### `det`

```fortran
d = det(a)
```

Returns the determinant of a square numeric matrix using a small dense
Gaussian-elimination backend.

### `eig`

```fortran
lambda = eig(a)
```

Returns eigenvalues of a real symmetric square matrix as a rank-1
`double precision` array sorted descending. General nonsymmetric eigenvalues
and eigenvectors are not implemented.

### `svd`

```fortran
s = svd(a)
```

Returns singular values of a real rank-2 matrix sorted descending. This uses
the eigendecomposition of `transpose(a)*a`; singular vectors are not returned.

### `qr`

```fortran
r = qr(a)
```

Returns the upper-triangular `R` factor from a modified Gram-Schmidt QR
factorization. The orthogonal `Q` factor is not returned.

### `lu`

```fortran
f = lu(a)
```

Returns a packed LU factorization matrix with `U` on and above the diagonal and
the subdiagonal entries of `L` below it. Partial row pivoting is used
internally, but the pivot vector is not returned.

### `pinv`

```fortran
b = pinv(a)
```

Returns a Moore-Penrose-style pseudoinverse for full-column-rank or
full-row-rank real dense matrices using normal equations. Rank-deficient
matrices are diagnosed rather than regularized.

### `cond`

```fortran
c = cond(a)
```

Returns the 2-norm condition estimate `max(svd(a))/min(svd(a))`. Singular
matrices return infinity.

### `norm`

```fortran
n = norm(a)
```

Returns the Euclidean norm for a vector and the Frobenius norm for a matrix.

### `triu`, `tril`, and `kron`

```fortran
u = triu(a)
u = triu(a, k)
l = tril(a)
l = tril(a, k)
k = kron(a, b)
```

`triu` and `tril` return the upper or lower triangle of a matrix, optionally
offset by diagonal `k`. `kron` returns the Kronecker product of two rank-2
numeric arrays.

### `outer_product`

```fortran
a = outer_product(u, v)
```

Returns `u * transpose(v)` for two rank-1 numeric arrays.

### Matrix predicates

```fortran
tf = is_square(a)
tf = is_diagonal(a)
tf = is_symmetric(a)
```

`is_square` checks shape only. `is_diagonal` and `is_symmetric` require numeric
rank-2 arrays and use exact comparisons.

### `transpose2`

```fortran
y = transpose2(x)
```

Returns the transpose of matrix `x`.

Arguments:

- `x`: rank-2 numeric array of shape `(nrow, ncol)`.

Result:

- rank-2 `double precision` array of shape `(ncol, nrow)`.

### `matmul2`

```fortran
c = matmul2(a, b)
```

Returns the matrix product `a * b`.

Arguments:

- `a`: rank-2 numeric array of shape `(m, k)`.
- `b`: rank-2 numeric array of shape `(k, n)`.

Result:

- rank-2 `double precision` array of shape `(m, n)`.

### `crossprod`

```fortran
c = crossprod(x)
c = crossprod(x, y)
```

Returns a crossproduct.

Arguments:

- `x`: rank-2 numeric array of shape `(nrow, xcols)`.
- `y`: optional rank-2 numeric array of shape `(nrow, ycols)`.

Result:

- If `y` is omitted, returns `transpose(x) * x`, shape `(xcols, xcols)`.
- If `y` is supplied, returns `transpose(x) * y`, shape `(xcols, ycols)`.

### `tcrossprod`

```fortran
c = tcrossprod(x)
c = tcrossprod(x, y)
```

Returns a transposed crossproduct.

Arguments:

- `x`: rank-2 numeric array of shape `(xrows, ncol)`.
- `y`: optional rank-2 numeric array of shape `(yrows, ncol)`.

Result:

- If `y` is omitted, returns `x * transpose(x)`, shape `(xrows, xrows)`.
- If `y` is supplied, returns `x * transpose(y)`, shape `(xrows, yrows)`.

### `col_sums`

```fortran
s = col_sums(x)
```

Arguments:

- `x`: rank-2 numeric array of shape `(nrow, ncol)`.

Result:

- rank-1 `double precision` array of length `ncol`, containing column sums.

### `col_means`

```fortran
mu = col_means(x)
```

Arguments:

- `x`: rank-2 numeric array of shape `(nrow, ncol)`.

Result:

- rank-1 `double precision` array of length `ncol`, containing column means.

### `center_cols`

```fortran
call center_cols(x, mean, out)
```

Subtracts one value from each column of `x`.

Arguments:

- `x`: rank-2 numeric input array of shape `(nrow, ncol)`.
- `mean`: rank-1 numeric input array of length `ncol`.
- `out`: rank-2 real output array of shape `(nrow, ncol)`.

## `stdlib_linalg`

`stdlib_linalg` is a compatibility subset of the Fortran stdlib linear-algebra
API. It currently exports `eye`, `diag`, `det`, `eig`, `svd`, `qr`, `lu`,
`pinv`, `cond`, `norm`, `triu`, `tril`, `kron`, `solve`, `inv`, `rank`,
`chol`, `trace`, `outer_product`, `is_square`, `is_diagonal`, `is_symmetric`,
and `is_invertible`.

These names use the same runtime implementations as `ofort_la_mod`. The subset
is intended to let simple stdlib-style code run in `ofort`; compiled programs
should use the real Fortran stdlib package.

## `ofort_io_mod`

The I/O module provides simple dependency-free readers for numeric text data.
It is intended for files that are easy to parse, such as whitespace-delimited
numeric matrices and simple comma-delimited files. It does not currently
implement quoted CSV fields.

### `read_matrix`

```fortran
call read_matrix(file, x)
call read_matrix(file, x, ncol=ncol)
call read_matrix(file, x, delimiter=",", header=.true., row_labels=labels)
```

Reads a numeric matrix from a text file and allocates the output matrix.

Arguments:

- `file`: character input file path.
- `x`: allocatable real rank-2 output array. The procedure allocates/replaces it
  with shape `(nrow, ncol)`.
- `ncol`: optional integer number of numeric columns. If omitted, the number of
  numeric columns is inferred from the first data row.
- `delimiter`: optional character delimiter. If omitted, runs of whitespace
  separate fields. For CSV-like files use `delimiter=","`.
- `header`: optional logical. If true, one non-comment, nonblank row after
  `skiprows` is skipped before data parsing.
- `skiprows`: optional integer number of physical input lines to skip first.
- `comment`: optional character comment marker. The default is `"#"`.
- `row_labels`: optional allocatable character rank-1 output array. If present,
  the first field of each data row is stored as a label and excluded from the
  numeric matrix.

Examples:

```fortran
real(8), allocatable :: x(:,:)
character(len=32), allocatable :: dates(:)

call read_matrix("x.txt", x)
call read_matrix("prices.csv", x, delimiter=",", header=.true., &
                 ncol=4, row_labels=dates)
```

### `read_vector`

```fortran
call read_vector(file, x)
call read_vector(file, x, delimiter=",", header=.true.)
```

Reads numeric fields from a text file into one rank-1 vector and allocates the
output vector.

Arguments:

- `file`: character input file path.
- `x`: allocatable real rank-1 output array.
- `delimiter`: optional character delimiter. If omitted, whitespace separates
  fields.
- `header`: optional logical. If true, one non-comment, nonblank row after
  `skiprows` is skipped before data parsing.
- `skiprows`: optional integer number of physical input lines to skip first.
- `comment`: optional character comment marker. The default is `"#"`.

## `stdlib_io`

`stdlib_io` is a compatibility subset of the Fortran stdlib I/O API. It
currently exports `loadtxt` and `savetxt`.

```fortran
call loadtxt(filename, array)
call loadtxt(filename, array, skiprows, max_rows, fmt, delimiter)
call loadtxt(filename, array, skiprows=1, max_rows=100, delimiter=",")
```

Reads a numeric text file into an allocatable rank-2 `double precision` array.
The implementation uses the same runtime reader as `ofort_io_mod::read_matrix`.

Supported arguments:

- `filename`: character input file path.
- `array`: allocatable real rank-2 output array.
- `skiprows`: optional integer number of physical input lines to skip first.
- `max_rows`: optional integer maximum number of data rows to read. A negative
  value means all rows.
- `fmt`: optional character format. Only `fmt="*"` is currently accepted.
- `delimiter`: optional single-character delimiter. If omitted, whitespace
  separates fields.

Compiled programs should use the real Fortran stdlib package for full
`stdlib_io` behavior.

### `savetxt`

```fortran
call savetxt(filename, array)
call savetxt(filename, array, delimiter, fmt, header, footer, comments)
call savetxt(filename, array, delimiter=",", header="x,y", comments="")
```

Writes a rank-2 numeric array to a text file. The file is overwritten.

Supported arguments:

- `filename`: character output file path.
- `array`: rank-2 numeric input array.
- `delimiter`: optional character delimiter. The default is one space.
- `fmt`: optional character format. Only `fmt="*"` is currently accepted.
- `header`: optional character header line.
- `footer`: optional character footer line.
- `comments`: optional character prefix for `header` and `footer`. The default
  is `"# "`.

The stdlib form accepting an already-open unit is not currently implemented.

## `ofort_statistics_mod`

The statistics module provides C-backed statistics routines for numeric vectors
and matrices. The procedures return `double precision` values or arrays.

### `mean`

```fortran
xmean = mean(x)
```

Arguments:

- `x`: rank-1 numeric array.

Result:

- arithmetic mean of `x`.

### `variance`

```fortran
xvar = variance(x)
```

Arguments:

- `x`: rank-1 numeric array with at least two observations.

Result:

- sample variance, dividing by `n - 1`.

### `sd`

```fortran
xsd = sd(x)
```

Arguments:

- `x`: rank-1 numeric array with at least two observations.

Result:

- sample standard deviation, dividing by `n - 1`.

### `cov`

```fortran
cxy = cov(x, y)
c = cov(x)
```

Arguments:

- `x`, `y`: rank-1 numeric arrays of equal length for the two-vector form.
- `x`: rank-2 numeric array for the matrix form, where columns are variables.

Result:

- two-vector form: sample covariance of `x` and `y`.
- matrix form: sample covariance matrix of the columns of `x`.

### `cor`

```fortran
rxy = cor(x, y)
r = cor(x)
```

Arguments:

- `x`, `y`: rank-1 numeric arrays of equal length for the two-vector form.
- `x`: rank-2 numeric array for the matrix form, where columns are variables.

Result:

- two-vector form: sample correlation of `x` and `y`.
- matrix form: sample correlation matrix of the columns of `x`.

### `median`

```fortran
xmedian = median(x)
```

Arguments:

- `x`: numeric array. The current implementation flattens the array.

Result:

- median of `x`. Even-length inputs return the average of the two middle
  sorted values.

### `moment`

```fortran
xmoment = moment(x, order)
xmoment = moment(x, order, center)
```

Arguments:

- `x`: numeric array. The current implementation flattens the array.
- `order`: integer moment order.
- `center`: optional real center. If omitted, the mean of `x` is used.

Result:

- average of `(x - center)**order`.

### `variance_given_mean`

```fortran
xvar = variance_given_mean(x, xmean)
```

Arguments:

- `x`: rank-1 numeric array with at least two observations.
- `xmean`: previously computed mean of `x`.

Result:

- sample variance, dividing by `n - 1`.

### `sd_given_mean`

```fortran
xsd = sd_given_mean(x, xmean)
```

Arguments:

- `x`: rank-1 numeric array with at least two observations.
- `xmean`: previously computed mean of `x`.

Result:

- sample standard deviation, dividing by `n - 1`.

### `calc_stats`

```fortran
call calc_stats(x, mean=xmean)
call calc_stats(x, mean=xmean, sd=xsd, var=xvar)
```

Computes vector statistics in one call.

Arguments:

- `x`: rank-1 numeric input array.
- `mean`: scalar real output.
- `sd`: optional scalar real output, sample standard deviation.
- `var`: optional scalar real output, sample variance.

At least `x` and `mean` are required.

### `calc_col_stats`

```fortran
call calc_col_stats(x, mean=mu, sd=xs, var=xvar)
call calc_col_stats(x, cov=covmat, corr=cormat)
call calc_col_stats(x, rms=rms, cov_zm=cov_zm, corr_zm=corr_zm)
```

Computes column statistics for a rank-2 numeric matrix.

Arguments:

- `x`: rank-2 numeric input array of shape `(nrow, ncol)`.
- `mean`: optional rank-1 real output of length `ncol`.
- `sd`: optional rank-1 real output of length `ncol`, sample standard
  deviations using centered data and denominator `nrow - 1`.
- `var`: optional rank-1 real output of length `ncol`, sample variances using
  centered data and denominator `nrow - 1`.
- `cov`: optional rank-2 real output of shape `(ncol, ncol)`, sample covariance
  matrix using centered data and denominator `nrow - 1`.
- `corr`: optional rank-2 real output of shape `(ncol, ncol)`, sample
  correlation matrix using centered data.
- `rms`: optional rank-1 real output of length `ncol`, root mean square using
  zero-mean formulas.
- `cov_zm`: optional rank-2 real output of shape `(ncol, ncol)`, zero-mean
  covariance matrix. It divides raw crossproducts by `nrow`.
- `corr_zm`: optional rank-2 real output of shape `(ncol, ncol)`, zero-mean
  correlation matrix.

At least one output argument is required. Centered covariance/correlation paths
use a centered workspace for performance. Zero-mean outputs are useful for
finance-style daily-return calculations where the mean is treated as zero.

### `pca`

```fortran
call pca(x, components, singular_values)
call pca(x, components, singular_values, x_mean)
```

Performs a limited PCA using eigendecomposition of the covariance matrix.

Arguments:

- `x`: rank-2 numeric input array with observations in rows and features in
  columns.
- `components`: rank-2 real output of shape `(ncomp, ncol)`. Components are
  stored as rows.
- `singular_values`: rank-1 real output of length `ncomp`.
- `x_mean`: optional rank-1 real output of length `ncol`.

Limitations:

- Uses a small in-process symmetric Jacobi eigensolver, not LAPACK.
- Supports up to 64 columns.
- `method` and `overwrite_x` are accepted and ignored.
- `err` is not supported.

### `pca_transform`

```fortran
call pca_transform(x, components, x_transformed)
call pca_transform(x, components, x_transformed, x_mean)
```

Computes `(x - x_mean) * transpose(components)`.

### `pca_inverse_transform`

```fortran
call pca_inverse_transform(x_reduced, components, x_reconstructed)
call pca_inverse_transform(x_reduced, components, x_reconstructed, x_mean)
```

Computes `x_reduced * components + x_mean`.

## `stdlib_stats`

`ofort` recognizes selected procedures from the Fortran stdlib `stdlib_stats`
module and maps them to the same runtime routines used by
`ofort_statistics_mod`.

Supported procedures:

- `mean(x)`: mean of a rank-1 numeric array.
- `var(x)`: sample variance of a rank-1 numeric array, equivalent to
  `variance(x)` in `ofort_statistics_mod`.
- `median(x)`: median of a numeric array.
- `moment(x, order)`, `moment(x, order, center)`: central moment of a numeric
  array.
- `cov(x, y)`: sample covariance of two rank-1 numeric arrays of equal size.
- `cov(x)`: covariance matrix of the columns of rank-2 numeric array `x`.
- `corr(x, y)`: correlation of two rank-1 numeric arrays of equal size,
  equivalent to `cor(x, y)` in `ofort_statistics_mod`.
- `corr(x)`: correlation matrix of the columns of rank-2 numeric array `x`.
- `pca`, `pca_transform`, and `pca_inverse_transform`: limited PCA support
  using the same implementation as `ofort_statistics_mod`.

Current limitations:

- This is not full stdlib coverage.
- `dim`, `mask`, and `corrected` arguments are not implemented.
- The initial target is double precision scalar results and rank-1/rank-2
  numeric array arguments.
- PCA uses the limited `ofort_statistics_mod` eigendecomposition backend.

Example:

```fortran
program main
use stdlib_stats, only: mean, var, cov, corr
implicit none
real(8) :: x(4), y(4)
x = [1.0d0, 2.0d0, 3.0d0, 4.0d0]
y = [2.0d0, 4.0d0, 6.0d0, 8.0d0]
print *, mean(x)
print *, var(x)
print *, cov(x, y)
print *, corr(x, y)
end program main
```

## `stdlib_stats_distribution_normal`

`ofort` recognizes a small double precision subset of the Fortran stdlib normal
distribution module.

Supported procedures:

- `rvs_normal()`: scalar standard normal variate.
- `rvs_normal(loc, scale)`: scalar normal variate with mean `loc` and standard
  deviation `scale`.
- `rvs_normal(array_size)`: rank-1 standard normal array.
- `rvs_normal(loc, scale, array_size)` and keyword spelling
  `rvs_normal(loc=..., scale=..., array_size=...)`: rank-1 normal array.
- `pdf_normal(x, loc, scale)`: normal probability density. Arguments may be
  scalar or rank-1 real arrays. Scalar arguments are broadcast.
- `cdf_normal(x, loc, scale)`: normal cumulative probability. Arguments may be
  scalar or rank-1 real arrays. Scalar arguments are broadcast.

Current limitations:

- This is not full stdlib coverage.
- Complex arguments, rank greater than 1 for `pdf_normal`/`cdf_normal`, and kind
  selection through `mold` are not implemented. `mold` is accepted in the
  `rvs_normal(array_size, mold)` form but the result is still `real(8)`.
- `scale <= 0` returns `NaN`.
