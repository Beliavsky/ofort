#include "ofort_internal.h"

#include <stdlib.h>
#include <string.h>

OfortValue make_integer(long long v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_INTEGER; r.kind = 4; r.v.i = v; r.v.i128 = (__int128)v; return r;
}

OfortValue make_integer_kind(long long v, int kind) {
    OfortValue r = make_integer(v);
    r.kind = kind > 0 ? kind : 4;
    if (r.kind == 16) r.v.i128 = (__int128)v;
    return r;
}

OfortValue make_integer128(__int128 v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_INTEGER;
    r.kind = 16;
    r.v.i128 = v;
    r.v.i = (long long)v;
    return r;
}

OfortValue make_real(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_REAL; r.kind = 4; r.v.r = v; return r;
}

OfortValue make_double(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_DOUBLE; r.kind = 8; r.v.r = v; return r;
}

OfortValue make_complex(double re, double im) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_COMPLEX; r.kind = 4; r.v.cx.re = re; r.v.cx.im = im; return r;
}

OfortValue make_complex_kind(double re, double im, int kind) {
    OfortValue r = make_complex(re, im);
    r.kind = kind > 0 ? kind : 4;
    return r;
}

OfortValue make_character(const char *s) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_CHARACTER; r.v.s = strdup(s ? s : ""); return r;
}

OfortValue make_logical(int b) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_LOGICAL; r.kind = 4; r.v.b = b ? 1 : 0; return r;
}

OfortValue make_void_val(void) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_VOID; return r;
}

double val_to_real(OfortValue v) {
    switch (v.type) {
        case FVAL_INTEGER: return (double)v.v.i;
        case FVAL_REAL: case FVAL_DOUBLE: return v.v.r;
        case FVAL_LOGICAL: return (double)v.v.b;
        case FVAL_COMPLEX: return v.v.cx.re;
        default: return 0.0;
    }
}

long long val_to_int(OfortValue v) {
    switch (v.type) {
        case FVAL_INTEGER: return v.v.i;
        case FVAL_REAL: case FVAL_DOUBLE: return (long long)v.v.r;
        case FVAL_LOGICAL: return (long long)v.v.b;
        case FVAL_COMPLEX: return (long long)v.v.cx.re;
        default: return 0;
    }
}

int val_to_logical(OfortValue v) {
    switch (v.type) {
        case FVAL_LOGICAL: return v.v.b;
        case FVAL_INTEGER: return v.v.i != 0;
        case FVAL_REAL: case FVAL_DOUBLE: return v.v.r != 0.0;
        default: return 0;
    }
}

void free_value(OfortValue *v) {
    if (v->type == FVAL_CHARACTER && v->v.s) {
        free(v->v.s); v->v.s = NULL;
    } else if (v->type == FVAL_ARRAY) {
        if (v->v.arr.data) {
            int i;
            for (i = 0; i < v->v.arr.len; i++) free_value(&v->v.arr.data[i]);
            free(v->v.arr.data); v->v.arr.data = NULL;
        }
        if (v->v.arr.real_data) { free(v->v.arr.real_data); v->v.arr.real_data = NULL; }
        if (v->v.arr.int_data) { free(v->v.arr.int_data); v->v.arr.int_data = NULL; }
    } else if (v->type == FVAL_DERIVED) {
        if (v->v.dt.fields) {
            int i;
            for (i = 0; i < v->v.dt.n_fields; i++) free_value(&v->v.dt.fields[i]);
            free(v->v.dt.fields); v->v.dt.fields = NULL;
        }
        if (v->v.dt.field_names) { free(v->v.dt.field_names); v->v.dt.field_names = NULL; }
    }
}

OfortValue copy_value(OfortValue v) {
    OfortValue r = v;
    if (v.type == FVAL_CHARACTER && v.v.s) {
        r.v.s = strdup(v.v.s);
    } else if (v.type == FVAL_ARRAY && v.v.arr.data) {
        int i;
        r.v.arr.data = NULL;
        r.v.arr.real_data = NULL;
        r.v.arr.int_data = NULL;
        r.v.arr.data = (OfortValue *)malloc(sizeof(OfortValue) * v.v.arr.cap);
        for (i = 0; i < v.v.arr.len; i++)
            r.v.arr.data[i] = copy_value(v.v.arr.data[i]);
    } else if (v.type == FVAL_ARRAY && v.v.arr.real_data) {
        r.v.arr.data = NULL;
        r.v.arr.real_data = NULL;
        r.v.arr.int_data = NULL;
        r.v.arr.real_data = (double *)malloc(sizeof(double) * v.v.arr.cap);
        if (r.v.arr.real_data) memcpy(r.v.arr.real_data, v.v.arr.real_data, sizeof(double) * v.v.arr.len);
    } else if (v.type == FVAL_ARRAY && v.v.arr.int_data) {
        r.v.arr.data = NULL;
        r.v.arr.real_data = NULL;
        r.v.arr.int_data = NULL;
        r.v.arr.int_data = (long long *)malloc(sizeof(long long) * v.v.arr.cap);
        if (r.v.arr.int_data) memcpy(r.v.arr.int_data, v.v.arr.int_data, sizeof(long long) * v.v.arr.len);
    } else if (v.type == FVAL_DERIVED && v.v.dt.fields) {
        int i;
        r.v.dt.fields = NULL;
        r.v.dt.field_names = NULL;
        r.v.dt.fields = (OfortValue *)malloc(sizeof(OfortValue) * v.v.dt.n_fields);
        r.v.dt.field_names = (char(*)[64])malloc(sizeof(char[64]) * v.v.dt.n_fields);
        for (i = 0; i < v.v.dt.n_fields; i++) {
            r.v.dt.fields[i] = copy_value(v.v.dt.fields[i]);
            strcpy(r.v.dt.field_names[i], v.v.dt.field_names[i]);
        }
    }
    return r;
}

OfortValue resize_character_value(OfortValue val, int char_len) {
    if (val.type != FVAL_CHARACTER || char_len <= 0) return val;
    char *buf = (char *)calloc((size_t)char_len + 1, 1);
    int src_len = val.v.s ? (int)strlen(val.v.s) : 0;
    int copy_len = src_len < char_len ? src_len : char_len;
    if (copy_len > 0) memcpy(buf, val.v.s, (size_t)copy_len);
    if (copy_len < char_len) memset(buf + copy_len, ' ', (size_t)(char_len - copy_len));
    free_value(&val);
    OfortValue resized = make_character(buf);
    free(buf);
    return resized;
}
