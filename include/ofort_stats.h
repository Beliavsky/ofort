#ifndef OFORT_STATS_H
#define OFORT_STATS_H

#ifdef __cplusplus
extern "C" {
#endif

double ofort_stats_mean_r8(const double *x, int n);
double ofort_stats_variance_r8(const double *x, int n);
double ofort_stats_sd_r8(const double *x, int n);
double ofort_stats_cov_r8(const double *x, const double *y, int n);
double ofort_stats_cor_r8(const double *x, const double *y, int n);
double ofort_stats_median_r8(const double *x, int n);
double ofort_stats_moment_r8(const double *x, int n, int order, double center);

#ifdef __cplusplus
}
#endif

#endif
