#ifndef OFORT_LAPACK_H
#define OFORT_LAPACK_H

#include <stddef.h>

#define OFORT_LAPACK_MAX_ARGS 16
typedef struct {
    const char *name;
    const char *types;
    const char *arguments[OFORT_LAPACK_MAX_ARGS];
    unsigned write_mask;
    unsigned read_mask;
} OfortLapackRoutine;

int ofort_lapack_find(const char *name);
const OfortLapackRoutine *ofort_lapack_routine(int id);
/* Validate scalar arguments and calculate storage requirements. Negative
   return values use LAPACK's INFO convention; no native call is made. */
int ofort_lapack_requirements(int id, void **args, size_t *lengths);
int ofort_lapack_call(int id, void **args, char *error, size_t error_size);

#endif
