/* Optional native LAPACK backend. The base interpreter has no LAPACK link dependency. */
#include "ofort_lapack.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include "ofort_lapack_signatures.inc"

int ofort_lapack_find(const char *name) {
    if (!name) return -1;
    for (size_t i = 0; i < sizeof(lapack_routines) / sizeof(lapack_routines[0]); i++) {
        const char *a = name, *b = lapack_routines[i].name;
        while (*a && *b && tolower((unsigned char)*a) == *b) { a++; b++; }
        if (!*a && !*b) return (int)i;
    }
    return -1;
}

const OfortLapackRoutine *ofort_lapack_routine(int id) {
    return id >= 0 && (size_t)id < sizeof(lapack_routines) / sizeof(lapack_routines[0])
        ? &lapack_routines[id] : NULL;
}

static int integer_argument(const OfortLapackRoutine *r, void **a, const char *name) {
    for (int i = 0; r->types[i]; i++)
        if (strcmp(r->arguments[i], name) == 0) return *(int *)a[i];
    return 0;
}

static char character_argument(const OfortLapackRoutine *r, void **a, const char *name) {
    for (int i = 0; r->types[i]; i++)
        if (strcmp(r->arguments[i], name) == 0) return (char)toupper((unsigned char)*(char *)a[i]);
    return '\0';
}

static void require_storage(const OfortLapackRoutine *r, size_t *lengths,
                            const char *name, size_t rows, size_t columns) {
    for (int i = 0; r->types[i]; i++)
        if (strcmp(r->arguments[i], name) == 0) lengths[i] = rows * columns;
}

int ofort_lapack_requirements(int id, void **a, size_t *lengths) {
    const OfortLapackRoutine *r = ofort_lapack_routine(id);
    int n, m, k, lda, lwork, query;
    if (!r) return -1;
    n = integer_argument(r, a, "n");
    m = integer_argument(r, a, "m");
    if (id == 0 || id == 2 || id == 3 || id == 4 || id == 5 || id == 9) m = n;
    k = m < n ? m : n;
    lda = integer_argument(r, a, "lda");
    lwork = integer_argument(r, a, "lwork");
    query = lwork == -1;
    for (int i = 0; r->types[i]; i++) {
        const char *p = r->arguments[i];
        lengths[i] = 1;
        if (r->types[i] == 'c') {
            char c = (char)toupper((unsigned char)*(char *)a[i]);
            const char *allowed = strcmp(p, "uplo") == 0 ? "UL" :
                (strcmp(p, "jobu") == 0 || strcmp(p, "jobvt") == 0) ? "ASON" : "NV";
            if (!strchr(allowed, c) || !c) return -(i + 1);
        }
        if (r->types[i] != 'i' || strcmp(p, "info") == 0) continue;
        int value = *(int *)a[i];
        if ((strcmp(p, "m") == 0 || strcmp(p, "n") == 0 || strcmp(p, "nrhs") == 0 ||
             strcmp(p, "k") == 0) && value < 0) return -(i + 1);
        if (strcmp(p, "lda") == 0 && value < (m > 1 ? m : 1)) return -(i + 1);
        if (strcmp(p, "ldb") == 0 && value < (n > 1 ? n : 1)) return -(i + 1);
        if (strcmp(p, "ldu") == 0) {
            char job = character_argument(r, a, "jobu");
            if (value < 1 || ((job == 'A' || job == 'S') && value < m)) return -(i + 1);
        }
        if (strcmp(p, "ldvt") == 0) {
            char job = character_argument(r, a, "jobvt");
            if (value < 1 || (job == 'A' && value < n) || (job == 'S' && value < k)) return -(i + 1);
        }
        if (strcmp(p, "ldvl") == 0 || strcmp(p, "ldvr") == 0) {
            char job = character_argument(r, a, strcmp(p, "ldvl") == 0 ? "jobvl" : "jobvr");
            if (value < 1 || (job == 'V' && value < n)) return -(i + 1);
        }
        if (strcmp(p, "lwork") == 0 && !query) {
            long long minimum = 1;
            if (id == 2) minimum = n;
            if (id == 4) minimum = 3LL*n - 1;
            if (id == 5) minimum = (character_argument(r,a,"jobvl") == 'V' ||
                                   character_argument(r,a,"jobvr") == 'V' ? 4LL : 3LL)*n;
            if (id == 6 || id == 7) minimum = n;
            if (id == 8) {
                long long wide = m > n ? m : n;
                minimum = 3LL*k + wide;
                if (minimum < 5LL*k) minimum = 5LL*k;
            }
            if (minimum < 1) minimum = 1;
            if (value < minimum) return -(i + 1);
        }
    }
    if (id == 7) {
        if (n > m) return -2;
        if (integer_argument(r,a,"k") > n) return -3;
    }
    if (id == 8 && character_argument(r,a,"jobu") == 'O' &&
        character_argument(r,a,"jobvt") == 'O') return -2;
    /* Workspace queries do not access matrix/vector data. */
    if (query) return 0;
    require_storage(r,lengths,"a",(size_t)lda,(size_t)n);
    require_storage(r,lengths,"ipiv",(size_t)k,1);
    require_storage(r,lengths,"b",(size_t)integer_argument(r,a,"ldb"),
                    (size_t)integer_argument(r,a,"nrhs"));
    require_storage(r,lengths,"work",(size_t)(lwork > 0 ? lwork : 1),1);
    require_storage(r,lengths,"w",(size_t)n,1);
    require_storage(r,lengths,"wr",(size_t)n,1);
    require_storage(r,lengths,"wi",(size_t)n,1);
    require_storage(r,lengths,"s",(size_t)k,1);
    require_storage(r,lengths,"tau",(size_t)(id == 7 ? integer_argument(r,a,"k") : k),1);
    if (id == 5) {
        if (character_argument(r,a,"jobvl") == 'V')
            require_storage(r,lengths,"vl",(size_t)integer_argument(r,a,"ldvl"),(size_t)n);
        if (character_argument(r,a,"jobvr") == 'V')
            require_storage(r,lengths,"vr",(size_t)integer_argument(r,a,"ldvr"),(size_t)n);
    }
    if (id == 8) {
        char u = character_argument(r,a,"jobu"), v = character_argument(r,a,"jobvt");
        if (u == 'A' || u == 'S') require_storage(r,lengths,"u",
            (size_t)integer_argument(r,a,"ldu"),(size_t)(u == 'A' ? m : k));
        if (v == 'A' || v == 'S') require_storage(r,lengths,"vt",
            (size_t)integer_argument(r,a,"ldvt"),(size_t)n);
    }
    return 0;
}

int ofort_lapack_call(int id, void **args, char *error, size_t error_size) {
    typedef void (*Dispatch)(int, void **);
    typedef int (*Version)(void);
    static Dispatch dispatch;
    if (!dispatch) {
        const char *configured = getenv("OFORT_LAPACK_LIBRARY");
        char path[4096];
        Version version;
#ifdef _WIN32
        HMODULE library;
        if (configured && *configured) snprintf(path,sizeof(path),"%s",configured);
        else {
            DWORD length = GetModuleFileNameA(NULL,path,sizeof(path));
            if (!length || length >= sizeof(path)) path[0] = '\0';
            char *slash = strrchr(path,'\\');
            if (slash) slash[1] = '\0'; else path[0] = '\0';
            size_t used = strlen(path);
            snprintf(path+used,sizeof(path)-used,"ofort_lapack_backend.dll");
        }
        library = LoadLibraryA(path);
        Dispatch candidate = library ? (Dispatch)(void *)GetProcAddress(library,"ofort_lapack_dispatch") : NULL;
        version = library ? (Version)(void *)GetProcAddress(library,"ofort_lapack_backend_version") : NULL;
#else
#ifdef __APPLE__
        const char *default_path = "./libofort_lapack_backend.dylib";
#else
        const char *default_path = "./libofort_lapack_backend.so";
#endif
        snprintf(path,sizeof(path),"%s",configured && *configured ? configured : default_path);
        void *library = dlopen(path,RTLD_NOW | RTLD_LOCAL);
        Dispatch candidate = library ? (Dispatch)dlsym(library,"ofort_lapack_dispatch") : NULL;
        version = library ? (Version)dlsym(library,"ofort_lapack_backend_version") : NULL;
#endif
        if (!candidate || !version || version() != 1) {
            snprintf(error,error_size,"Cannot load compatible native LAPACK backend '%s'; build with make -f bindings/lapack/makefile or set OFORT_LAPACK_LIBRARY",path);
#ifdef _WIN32
            if (library) FreeLibrary(library);
#else
            if (library) dlclose(library);
#endif
            return -1;
        }
        dispatch = candidate;
    }
    dispatch(id,args);
    return 0;
}
