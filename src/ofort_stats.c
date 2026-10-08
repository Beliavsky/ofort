#include "ofort_stats.h"

#include <math.h>
#include <stdlib.h>

static int cmp_double_ascending(const void *a, const void *b) {
    double da = *(const double *)a;
    double db = *(const double *)b;
    return (da > db) - (da < db);
}

double ofort_stats_mean_r8(const double *x, int n) {
    double sum = 0.0;
    if (!x || n <= 0) return NAN;
    for (int i = 0; i < n; i++) sum += x[i];
    return sum / (double)n;
}

double ofort_stats_variance_r8(const double *x, int n) {
    double mean;
    double ss = 0.0;
    if (!x || n < 2) return NAN;
    mean = ofort_stats_mean_r8(x, n);
    for (int i = 0; i < n; i++) {
        double d = x[i] - mean;
        ss += d * d;
    }
    return ss / (double)(n - 1);
}

double ofort_stats_sd_r8(const double *x, int n) {
    double v = ofort_stats_variance_r8(x, n);
    return isnan(v) ? NAN : sqrt(v);
}

double ofort_stats_cov_r8(const double *x, const double *y, int n) {
    double mx;
    double my;
    double ss = 0.0;
    if (!x || !y || n < 2) return NAN;
    mx = ofort_stats_mean_r8(x, n);
    my = ofort_stats_mean_r8(y, n);
    for (int i = 0; i < n; i++) ss += (x[i] - mx) * (y[i] - my);
    return ss / (double)(n - 1);
}

double ofort_stats_cor_r8(const double *x, const double *y, int n) {
    double c;
    double vx;
    double vy;
    double denom;
    if (!x || !y || n < 2) return NAN;
    c = ofort_stats_cov_r8(x, y, n);
    vx = ofort_stats_variance_r8(x, n);
    vy = ofort_stats_variance_r8(y, n);
    denom = sqrt(vx * vy);
    if (denom == 0.0 || isnan(denom)) return NAN;
    return c / denom;
}

double ofort_stats_median_r8(const double *x, int n) {
    double *work;
    double result;
    if (!x || n <= 0) return NAN;
    work = (double *)malloc((size_t)n * sizeof(*work));
    if (!work) return NAN;
    for (int i = 0; i < n; i++) work[i] = x[i];
    qsort(work, (size_t)n, sizeof(*work), cmp_double_ascending);
    if (n % 2) result = work[n / 2];
    else result = 0.5 * (work[n / 2 - 1] + work[n / 2]);
    free(work);
    return result;
}

double ofort_stats_moment_r8(const double *x, int n, int order, double center) {
    double sum = 0.0;
    if (!x || n <= 0 || order < 0) return NAN;
    for (int i = 0; i < n; i++) sum += pow(x[i] - center, (double)order);
    return sum / (double)n;
}
