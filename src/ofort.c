/*
 * OfflinAi Fortran Interpreter — single-file implementation.
 * Lexer -> Parser -> Tree-walking interpreter.
 *
 * Supports: Fortran 90/95/2003 subset — INTEGER, REAL, DOUBLE PRECISION,
 * CHARACTER, LOGICAL, COMPLEX, arrays (1-based, multi-dim, allocatable),
 * derived types, modules, subroutines, functions with INTENT/RESULT,
 * DO/DO WHILE, IF/ELSE IF/ELSE, SELECT CASE, intrinsic functions,
 * formatted I/O (PRINT/WRITE/READ), string concatenation (//), etc.
 */

#include "ofort.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <ctype.h>
#include <stdarg.h>
#include <setjmp.h>
#include <float.h>
#include <limits.h>
#include <stdint.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif

/* ══════════════════════════════════════════════
 *  Interpreter state
 * ══════════════════════════════════════════════ */

typedef struct {
    char name[256];
    OfortValue val;
    int is_parameter; /* PARAMETER = const */
    int intent;       /* 0=none,1=IN,2=OUT,3=INOUT */
    int char_len;     /* declared CHARACTER length, 0 if not CHARACTER */
    int present;      /* 0 for absent OPTIONAL dummy arguments */
    int is_allocatable;
    int is_pointer;
    int is_target;
    int is_protected;
    int is_save;
    int is_implicit_save;
    int pointer_associated;
    char pointer_target[256];
    int pointer_has_slice;
    int pointer_slice_start;
    int pointer_slice_end;
} OfortVar;

typedef struct OfortScope {
    OfortVar vars[OFORT_MAX_VARS];
    int n_vars;
    int implicit_none;
    char implicit_types[26];
    struct OfortScope *parent;
} OfortScope;

typedef struct {
    char name[256];
    OfortNode *node;
    int is_function; /* 1=function, 0=subroutine */
    char module_name[256]; /* "" if not in a module */
    OfortVar saved_vars[OFORT_MAX_VARS];
    int n_saved_vars;
} OfortFunc;

typedef struct {
    char name[128];
    char field_names[OFORT_MAX_FIELDS][64];
    OfortValType field_types[OFORT_MAX_FIELDS];
    int field_char_lens[OFORT_MAX_FIELDS];
    int n_fields;
} OfortTypeDef;

typedef struct {
    char name[128];
    OfortFunc funcs[OFORT_MAX_FUNCS];
    int n_funcs;
    OfortVar vars[OFORT_MAX_VARS];
    int var_public[OFORT_MAX_VARS];
    int n_vars;
    OfortTypeDef types[32];
    int n_types;
    int default_private;
} OfortModule;

typedef struct {
    int unit;
    char path[512];
    int stream_pos;
} OfortUnitFile;

struct OfortInterpreter {
    /* output */
    char output[OFORT_MAX_OUTPUT];
    int out_len;
    char error[4096];
    char warnings[4096];
    int warn_len;
    int warnings_enabled;
    int fast_mode;
    int line_profile_enabled;
    double *line_profile_seconds;
    int *line_profile_counts;
    int line_profile_nlines;
    OfortTiming timing;
    /* tokens */
    OfortToken tokens[OFORT_MAX_TOKENS];
    int n_tokens;
    int tok_pos;
    /* AST */
    OfortNode *ast;
    /* runtime */
    OfortScope *global_scope;
    OfortScope *current_scope;
    OfortFunc funcs[OFORT_MAX_FUNCS];
    int n_funcs;
    /* modules */
    OfortModule modules[OFORT_MAX_MODULES];
    int n_modules;
    /* derived type definitions */
    OfortTypeDef type_defs[64];
    int n_type_defs;
    /* simple external-unit file table */
    OfortUnitFile unit_files[32];
    int n_unit_files;
    /* control flow */
    int returning;
    OfortValue return_val;
    int exiting;     /* EXIT from DO loop */
    int cycling;     /* CYCLE in DO loop */
    int stopping;    /* STOP statement */
    /* error recovery */
    jmp_buf err_jmp;
    int has_error;
    /* source */
    const char *source;
    int current_line;
    int print_expr_statements;
    int suppress_output;
    int command_argc;
    char command_args[OFORT_MAX_PARAMS][OFORT_MAX_STRLEN];
    int procedure_depth;
    /* node pool for memory management */
    OfortNode **node_pool;
    int node_pool_len;
    int node_pool_cap;
};

/* ── Forward declarations ────────────────────── */
static void ofort_error(OfortInterpreter *I, const char *fmt, ...);
static OfortValue eval_node(OfortInterpreter *I, OfortNode *n);
static const char *type_token_intrinsic_name(OfortTokenType t);
static void exec_node(OfortInterpreter *I, OfortNode *n);
static OfortValue call_intrinsic(OfortInterpreter *I, const char *name, OfortValue *args, int nargs,
                                char arg_names[OFORT_MAX_PARAMS][256]);
static int is_intrinsic(const char *name);

static double ofort_monotonic_seconds(void) {
#ifdef _WIN32
    LARGE_INTEGER counter;
    LARGE_INTEGER frequency;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&frequency);
    return (double)counter.QuadPart / (double)frequency.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
#endif
}

static void clear_timing(OfortInterpreter *I) {
    if (I) memset(&I->timing, 0, sizeof(I->timing));
}

static int count_source_lines_text(const char *source) {
    int n = 1;
    if (!source || source[0] == '\0') return 0;
    for (const char *p = source; *p; p++) {
        if (*p == '\n' && p[1] != '\0') n++;
    }
    return n;
}

static void clear_line_profile(OfortInterpreter *I) {
    if (!I) return;
    free(I->line_profile_seconds);
    free(I->line_profile_counts);
    I->line_profile_seconds = NULL;
    I->line_profile_counts = NULL;
    I->line_profile_nlines = 0;
}

static int prepare_line_profile(OfortInterpreter *I, const char *source) {
    int nlines;
    clear_line_profile(I);
    if (!I || !I->line_profile_enabled) return 0;
    nlines = count_source_lines_text(source);
    if (nlines <= 0) return 0;
    I->line_profile_seconds = (double *)calloc((size_t)nlines + 1, sizeof(double));
    I->line_profile_counts = (int *)calloc((size_t)nlines + 1, sizeof(int));
    if (!I->line_profile_seconds || !I->line_profile_counts) {
        clear_line_profile(I);
        return -1;
    }
    I->line_profile_nlines = nlines;
    return 0;
}

static int node_is_profiled_statement(const OfortNode *n) {
    if (!n || n->line <= 0) return 0;
    switch (n->type) {
    case FND_VARDECL:
    case FND_PARAMDECL:
    case FND_ASSIGN:
    case FND_POINTER_ASSIGN:
    case FND_CALL:
    case FND_PRINT:
    case FND_WRITE:
    case FND_READ_STMT:
    case FND_OPEN:
    case FND_CLOSE:
    case FND_ALLOCATE:
    case FND_DEALLOCATE:
    case FND_RETURN:
    case FND_EXIT:
    case FND_CYCLE:
    case FND_STOP:
    case FND_EXPR_STMT:
        return 1;
    default:
        return 0;
    }
}

static void add_line_profile_time(OfortInterpreter *I, int line, double seconds) {
    if (!I || !I->line_profile_enabled) return;
    if (line <= 0 || line > I->line_profile_nlines) return;
    if (!I->line_profile_seconds || !I->line_profile_counts) return;
    I->line_profile_seconds[line] += seconds;
    I->line_profile_counts[line]++;
}

/* ── Helpers ─────────────────────────────────── */

static void copy_cstr(char *dst, size_t dst_size, const char *src) {
    size_t len;
    if (dst_size == 0) return;
    if (!src) src = "";
    len = strlen(src);
    if (len >= dst_size) len = dst_size - 1;
    if (len > 0) memcpy(dst, src, len);
    dst[len] = '\0';
}

static void out_append_raw(OfortInterpreter *I, const char *s) {
    int len = (int)strlen(s);
    if (I->out_len + len >= OFORT_MAX_OUTPUT - 1) len = OFORT_MAX_OUTPUT - 1 - I->out_len;
    if (len > 0) { memcpy(I->output + I->out_len, s, len); I->out_len += len; }
    I->output[I->out_len] = '\0';
}

static void out_append(OfortInterpreter *I, const char *s) {
    if (!I->suppress_output) {
        out_append_raw(I, s);
    }
}

static void out_appendf(OfortInterpreter *I, const char *fmt, ...) {
    char buf[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    out_append(I, buf);
}

static int infer_error_line(const char *message) {
    const char *p = message;

    while ((p = strstr(p, "line ")) != NULL) {
        const char *n = p + 5;
        if (isdigit((unsigned char)*n)) {
            return atoi(n);
        }
        p = n;
    }

    return 0;
}

static void append_source_line_to_error(OfortInterpreter *I, int line) {
    const char *p;
    const char *start;
    const char *end;
    int current = 1;
    int used;

    if (!I->source || line <= 0) {
        return;
    }

    p = I->source;
    while (*p && current < line) {
        if (*p == '\n') {
            current++;
        }
        p++;
    }

    if (current != line || !*p) {
        return;
    }

    start = p;
    end = start;
    while (*end && *end != '\n' && *end != '\r') {
        end++;
    }

    used = (int)strlen(I->error);
    if (used < (int)sizeof(I->error) - 1) {
        snprintf(I->error + used, sizeof(I->error) - (size_t)used,
                 "\nline %d: %.*s", line, (int)(end - start), start);
    }
}

static void ofort_error(OfortInterpreter *I, const char *fmt, ...) {
    int line;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(I->error, sizeof(I->error), fmt, ap);
    va_end(ap);
    line = I->current_line > 0 ? I->current_line : infer_error_line(I->error);
    append_source_line_to_error(I, line);
    I->has_error = 1;
    longjmp(I->err_jmp, 1);
}

static void append_source_line_to_warning(OfortInterpreter *I, int line) {
    const char *p;
    const char *start;
    const char *end;
    int current = 1;

    if (!I->source || line <= 0 || I->warn_len >= (int)sizeof(I->warnings) - 1) {
        return;
    }

    p = I->source;
    while (*p && current < line) {
        if (*p == '\n') current++;
        p++;
    }
    if (current != line || !*p) return;

    start = p;
    end = start;
    while (*end && *end != '\n' && *end != '\r') end++;

    I->warn_len += snprintf(I->warnings + I->warn_len,
                            sizeof(I->warnings) - (size_t)I->warn_len,
                            "line %d: %.*s\n", line, (int)(end - start), start);
    if (I->warn_len >= (int)sizeof(I->warnings)) {
        I->warn_len = (int)sizeof(I->warnings) - 1;
        I->warnings[I->warn_len] = '\0';
    }
}

static void ofort_warning(OfortInterpreter *I, int line, const char *fmt, ...) {
    va_list ap;
    int written;

    if (!I || !I->warnings_enabled || I->warn_len >= (int)sizeof(I->warnings) - 1) return;
    va_start(ap, fmt);
    written = vsnprintf(I->warnings + I->warn_len,
                        sizeof(I->warnings) - (size_t)I->warn_len, fmt, ap);
    va_end(ap);
    if (written < 0) return;
    if (written >= (int)sizeof(I->warnings) - I->warn_len) {
        I->warn_len = (int)sizeof(I->warnings) - 1;
        I->warnings[I->warn_len] = '\0';
        return;
    }
    I->warn_len += written;
    if (I->warn_len < (int)sizeof(I->warnings) - 1) {
        I->warnings[I->warn_len++] = '\n';
        I->warnings[I->warn_len] = '\0';
    }
    append_source_line_to_warning(I, line);
}

/* ── String upper-case helper (for case-insensitive matching) ── */
static void str_upper(char *dst, const char *src, int maxlen) {
    int i;
    for (i = 0; i < maxlen - 1 && src[i]; i++)
        dst[i] = (char)toupper((unsigned char)src[i]);
    dst[i] = '\0';
}

__attribute__((unused))
static int str_eq_nocase(const char *a, const char *b) {
    while (*a && *b) {
        if (toupper((unsigned char)*a) != toupper((unsigned char)*b)) return 0;
        a++; b++;
    }
    return *a == *b;
}

static int name_in_list_nocase(const char *name, char names[OFORT_MAX_PARAMS][256], int n_names) {
    for (int i = 0; i < n_names; i++) {
        if (str_eq_nocase(name, names[i])) return 1;
    }
    return 0;
}

/* ── Value constructors ─────────────────────── */
static OfortValue make_integer(long long v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_INTEGER; r.kind = 4; r.v.i = v; return r;
}
static OfortValue make_integer_kind(long long v, int kind) {
    OfortValue r = make_integer(v);
    r.kind = kind > 0 ? kind : 4;
    return r;
}
static OfortValue make_real(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_REAL; r.kind = 4; r.v.r = v; return r;
}
static OfortValue make_double(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_DOUBLE; r.kind = 8; r.v.r = v; return r;
}
static OfortValue make_complex(double re, double im) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_COMPLEX; r.kind = 4; r.v.cx.re = re; r.v.cx.im = im; return r;
}
static OfortValue make_complex_kind(double re, double im, int kind) {
    OfortValue r = make_complex(re, im);
    r.kind = kind > 0 ? kind : 4;
    return r;
}
static OfortValue make_character(const char *s) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_CHARACTER; r.v.s = strdup(s ? s : ""); return r;
}
static OfortValue make_logical(int b) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_LOGICAL; r.v.b = b ? 1 : 0; return r;
}
static OfortValue make_void_val(void) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_VOID; return r;
}

static double val_to_real(OfortValue v) {
    switch (v.type) {
        case FVAL_INTEGER: return (double)v.v.i;
        case FVAL_REAL: case FVAL_DOUBLE: return v.v.r;
        case FVAL_LOGICAL: return (double)v.v.b;
        case FVAL_COMPLEX: return v.v.cx.re;
        default: return 0.0;
    }
}
static long long val_to_int(OfortValue v) {
    switch (v.type) {
        case FVAL_INTEGER: return v.v.i;
        case FVAL_REAL: case FVAL_DOUBLE: return (long long)v.v.r;
        case FVAL_LOGICAL: return (long long)v.v.b;
        case FVAL_COMPLEX: return (long long)v.v.cx.re;
        default: return 0;
    }
}
static int val_to_logical(OfortValue v) {
    switch (v.type) {
        case FVAL_LOGICAL: return v.v.b;
        case FVAL_INTEGER: return v.v.i != 0;
        case FVAL_REAL: case FVAL_DOUBLE: return v.v.r != 0.0;
        default: return 0;
    }
}

static void free_value(OfortValue *v) {
    if (v->type == FVAL_CHARACTER && v->v.s) {
        free(v->v.s); v->v.s = NULL;
    } else if (v->type == FVAL_ARRAY && v->v.arr.data) {
        int i;
        for (i = 0; i < v->v.arr.len; i++) free_value(&v->v.arr.data[i]);
        free(v->v.arr.data); v->v.arr.data = NULL;
    } else if (v->type == FVAL_DERIVED) {
        if (v->v.dt.fields) {
            int i;
            for (i = 0; i < v->v.dt.n_fields; i++) free_value(&v->v.dt.fields[i]);
            free(v->v.dt.fields); v->v.dt.fields = NULL;
        }
        if (v->v.dt.field_names) { free(v->v.dt.field_names); v->v.dt.field_names = NULL; }
    }
}

static OfortValue copy_value(OfortValue v) {
    OfortValue r = v;
    if (v.type == FVAL_CHARACTER && v.v.s) {
        r.v.s = strdup(v.v.s);
    } else if (v.type == FVAL_ARRAY && v.v.arr.data) {
        int i;
        r.v.arr.data = (OfortValue *)malloc(sizeof(OfortValue) * v.v.arr.cap);
        for (i = 0; i < v.v.arr.len; i++)
            r.v.arr.data[i] = copy_value(v.v.arr.data[i]);
    } else if (v.type == FVAL_DERIVED && v.v.dt.fields) {
        int i;
        r.v.dt.fields = (OfortValue *)malloc(sizeof(OfortValue) * v.v.dt.n_fields);
        r.v.dt.field_names = (char(*)[64])malloc(sizeof(char[64]) * v.v.dt.n_fields);
        for (i = 0; i < v.v.dt.n_fields; i++) {
            r.v.dt.fields[i] = copy_value(v.v.dt.fields[i]);
            strcpy(r.v.dt.field_names[i], v.v.dt.field_names[i]);
        }
    }
    return r;
}

static OfortValue resize_character_value(OfortValue val, int char_len) {
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

/* ── Node allocation (tracked for cleanup) ───── */
static OfortNode *alloc_node(OfortInterpreter *I, OfortNodeType type) {
    OfortNode *n = (OfortNode *)calloc(1, sizeof(OfortNode));
    if (!n) ofort_error(I, "Out of memory");
    n->type = type;
    /* track for cleanup */
    if (I->node_pool_len >= I->node_pool_cap) {
        I->node_pool_cap = I->node_pool_cap ? I->node_pool_cap * 2 : 256;
        I->node_pool = (OfortNode **)realloc(I->node_pool, sizeof(OfortNode *) * I->node_pool_cap);
    }
    I->node_pool[I->node_pool_len++] = n;
    return n;
}

/* ── Scope management ────────────────────────── */
static OfortScope *push_scope(OfortInterpreter *I) {
    OfortScope *s = (OfortScope *)calloc(1, sizeof(OfortScope));
    s->parent = I->current_scope;
    if (s->parent) {
        s->implicit_none = s->parent->implicit_none;
        memcpy(s->implicit_types, s->parent->implicit_types, sizeof(s->implicit_types));
    }
    I->current_scope = s;
    return s;
}

static void set_scope_explicit_typing(OfortScope *s) {
    if (!s) return;
    s->implicit_none = 1;
    memset(s->implicit_types, 0, sizeof(s->implicit_types));
}

static void set_scope_legacy_implicit_typing(OfortScope *s) {
    if (!s) return;
    s->implicit_none = 0;
    for (int i = 0; i < 26; i++) s->implicit_types[i] = 'R';
    for (int i = 'I' - 'A'; i <= 'N' - 'A'; i++) s->implicit_types[i] = 'I';
}

static void pop_scope(OfortInterpreter *I) {
    OfortScope *s = I->current_scope;
    if (!s) return;
    I->current_scope = s->parent;
    /* free vars */
    int i;
    for (i = 0; i < s->n_vars; i++) free_value(&s->vars[i].val);
    free(s);
}

static OfortVar *find_var(OfortInterpreter *I, const char *name) {
    OfortScope *s = I->current_scope;
    char upper[256];
    str_upper(upper, name, 256);
    while (s) {
        int i;
        for (i = 0; i < s->n_vars; i++) {
            char vu[256];
            str_upper(vu, s->vars[i].name, 256);
            if (strcmp(upper, vu) == 0) return &s->vars[i];
        }
        s = s->parent;
    }
    return NULL;
}

static int current_scope_has_implicit_none(OfortInterpreter *I) {
    return I->current_scope && I->current_scope->implicit_none;
}

static OfortValType implicit_type_for_name(OfortInterpreter *I, const char *name, int *has_type) {
    char c = name && name[0] ? (char)toupper((unsigned char)name[0]) : '\0';
    int idx = (c >= 'A' && c <= 'Z') ? c - 'A' : -1;
    OfortScope *s = I->current_scope;
    if (has_type) *has_type = 0;
    while (s && idx >= 0) {
        char code = s->implicit_types[idx];
        if (code) {
            if (has_type) *has_type = 1;
            switch (code) {
                case 'I': return FVAL_INTEGER;
                case 'R': return FVAL_REAL;
                case 'D': return FVAL_DOUBLE;
                case 'L': return FVAL_LOGICAL;
                case 'C': return FVAL_CHARACTER;
                default: break;
            }
        }
        s = s->parent;
    }
    return FVAL_VOID;
}

static const char *value_type_name(OfortValType type) {
    switch (type) {
        case FVAL_INTEGER: return "INTEGER";
        case FVAL_REAL: return "REAL";
        case FVAL_DOUBLE: return "DOUBLE PRECISION";
        case FVAL_COMPLEX: return "COMPLEX";
        case FVAL_CHARACTER: return "CHARACTER";
        case FVAL_LOGICAL: return "LOGICAL";
        case FVAL_ARRAY: return "ARRAY";
        case FVAL_DERIVED: return "DERIVED";
        case FVAL_VOID: return "VOID";
        default: return "UNKNOWN";
    }
}

static int is_numeric_type(OfortValType type) {
    return type == FVAL_INTEGER || type == FVAL_REAL ||
           type == FVAL_DOUBLE || type == FVAL_COMPLEX;
}

static OfortValue coerce_assignment_value(OfortInterpreter *I, const char *name,
                                          OfortValType target_type, OfortValue val) {
    if (target_type == val.type) {
        return val;
    }

    if (is_numeric_type(target_type) && is_numeric_type(val.type)) {
        OfortValue converted;
        memset(&converted, 0, sizeof(converted));
        switch (target_type) {
            case FVAL_INTEGER:
                converted = make_integer(val_to_int(val));
                break;
            case FVAL_REAL:
                converted = make_real(val_to_real(val));
                break;
            case FVAL_DOUBLE:
                converted = make_double(val_to_real(val));
                break;
            case FVAL_COMPLEX:
                if (val.type == FVAL_COMPLEX) converted = make_complex(val.v.cx.re, val.v.cx.im);
                else converted = make_complex(val_to_real(val), 0.0);
                break;
            default:
                converted = val;
                break;
        }
        free_value(&val);
        return converted;
    }

    ofort_error(I, "Cannot assign %s to %s variable '%s'",
                value_type_name(val.type), value_type_name(target_type), name);
    return val;
}

static OfortVar *set_var(OfortInterpreter *I, const char *name, OfortValue val) {
    /* look in current scope first */
    OfortScope *s = I->current_scope;
    char upper[256];
    str_upper(upper, name, 256);
    int i;
    for (i = 0; i < s->n_vars; i++) {
        char vu[256];
        str_upper(vu, s->vars[i].name, 256);
        if (strcmp(upper, vu) == 0) {
            val = coerce_assignment_value(I, name, s->vars[i].val.type, val);
            if (s->vars[i].is_parameter)
                ofort_error(I, "Cannot assign to PARAMETER '%s'", name);
            if (s->vars[i].is_protected)
                ofort_error(I, "Cannot assign to PROTECTED variable '%s'", name);
            val = resize_character_value(val, s->vars[i].char_len);
            free_value(&s->vars[i].val);
            s->vars[i].val = val;
            return &s->vars[i];
        }
    }
    /* look in parent scopes */
    OfortScope *ps = s->parent;
    while (ps) {
        for (i = 0; i < ps->n_vars; i++) {
            char vu[256];
            str_upper(vu, ps->vars[i].name, 256);
            if (strcmp(upper, vu) == 0) {
                if (ps->vars[i].is_parameter)
                    ofort_error(I, "Cannot assign to PARAMETER '%s'", name);
                if (ps->vars[i].is_protected)
                    ofort_error(I, "Cannot assign to PROTECTED variable '%s'", name);
                val = coerce_assignment_value(I, name, ps->vars[i].val.type, val);
                val = resize_character_value(val, ps->vars[i].char_len);
                free_value(&ps->vars[i].val);
                ps->vars[i].val = val;
                return &ps->vars[i];
            }
        }
        ps = ps->parent;
    }
    /* create new in current scope */
    if (current_scope_has_implicit_none(I)) {
        free_value(&val);
        ofort_error(I, "Variable '%s' has no implicit type", name);
    }
    int has_implicit_type = 0;
    OfortValType implicit_type = implicit_type_for_name(I, name, &has_implicit_type);
    if (has_implicit_type) {
        val = coerce_assignment_value(I, name, implicit_type, val);
        val = resize_character_value(val, implicit_type == FVAL_CHARACTER ? OFORT_MAX_STRLEN - 1 : 0);
    }
    if (s->n_vars >= OFORT_MAX_VARS) ofort_error(I, "Too many variables");
    OfortVar *v = &s->vars[s->n_vars++];
    copy_cstr(v->name, sizeof(v->name), name);
    v->val = val;
    v->is_parameter = 0;
    v->intent = 0;
    v->char_len = val.type == FVAL_CHARACTER && val.v.s ? (int)strlen(val.v.s) : 0;
    v->present = 1;
    v->is_allocatable = 0;
    v->is_pointer = 0;
    v->is_target = 0;
    v->is_protected = 0;
    v->is_save = 0;
    v->is_implicit_save = 0;
    v->pointer_associated = 0;
    v->pointer_target[0] = '\0';
    v->pointer_has_slice = 0;
    v->pointer_slice_start = 0;
    v->pointer_slice_end = 0;
    return v;
}

static OfortVar *declare_var(OfortInterpreter *I, const char *name, OfortValue val) {
    OfortScope *s = I->current_scope;
    if (s->n_vars >= OFORT_MAX_VARS) ofort_error(I, "Too many variables");
    /* check for duplicate in current scope */
    char upper[256];
    str_upper(upper, name, 256);
    int i;
    for (i = 0; i < s->n_vars; i++) {
        char vu[256];
        str_upper(vu, s->vars[i].name, 256);
        if (strcmp(upper, vu) == 0) {
            free_value(&s->vars[i].val);
            s->vars[i].val = val;
            s->vars[i].char_len = val.type == FVAL_CHARACTER && val.v.s ? (int)strlen(val.v.s) : 0;
            s->vars[i].present = val.type != FVAL_VOID;
            return &s->vars[i];
        }
    }
    OfortVar *v = &s->vars[s->n_vars++];
    copy_cstr(v->name, sizeof(v->name), name);
    v->val = val;
    v->is_parameter = 0;
    v->intent = 0;
    v->char_len = val.type == FVAL_CHARACTER && val.v.s ? (int)strlen(val.v.s) : 0;
    v->present = val.type != FVAL_VOID;
    v->is_allocatable = 0;
    v->is_pointer = 0;
    v->is_target = 0;
    v->is_protected = 0;
    v->is_save = 0;
    v->is_implicit_save = 0;
    v->pointer_associated = 0;
    v->pointer_target[0] = '\0';
    v->pointer_has_slice = 0;
    v->pointer_slice_start = 0;
    v->pointer_slice_end = 0;
    return v;
}

/* ── Function lookup ─────────────────────────── */
static OfortVar *declare_absent_optional_var(OfortInterpreter *I, const char *name) {
    OfortVar *v = declare_var(I, name, make_void_val());
    v->present = 0;
    return v;
}

static OfortFunc *find_func(OfortInterpreter *I, const char *name) {
    char upper[256];
    str_upper(upper, name, 256);
    int i;
    for (i = 0; i < I->n_funcs; i++) {
        char fu[256];
        str_upper(fu, I->funcs[i].name, 256);
        if (strcmp(upper, fu) == 0) return &I->funcs[i];
    }
    return NULL;
}

static void register_func(OfortInterpreter *I, const char *name, OfortNode *node, int is_function) {
    if (I->n_funcs >= OFORT_MAX_FUNCS) ofort_error(I, "Too many functions/subroutines");
    OfortFunc *f = &I->funcs[I->n_funcs++];
    copy_cstr(f->name, sizeof(f->name), name);
    f->node = node;
    f->is_function = is_function;
    f->module_name[0] = '\0';
    f->n_saved_vars = 0;
}

static OfortVar *find_saved_var(OfortFunc *func, const char *name) {
    char upper[256];
    str_upper(upper, name, 256);
    for (int i = 0; i < func->n_saved_vars; i++) {
        char vu[256];
        str_upper(vu, func->saved_vars[i].name, 256);
        if (strcmp(upper, vu) == 0) return &func->saved_vars[i];
    }
    return NULL;
}

static void restore_saved_vars(OfortInterpreter *I, OfortFunc *func) {
    for (int i = 0; i < func->n_saved_vars; i++) {
        OfortVar *v = declare_var(I, func->saved_vars[i].name, copy_value(func->saved_vars[i].val));
        v->is_parameter = func->saved_vars[i].is_parameter;
        v->intent = func->saved_vars[i].intent;
        v->char_len = func->saved_vars[i].char_len;
        v->present = func->saved_vars[i].present;
        v->is_allocatable = func->saved_vars[i].is_allocatable;
        v->is_pointer = func->saved_vars[i].is_pointer;
        v->is_target = func->saved_vars[i].is_target;
        v->is_protected = func->saved_vars[i].is_protected;
        v->is_save = 1;
        v->is_implicit_save = func->saved_vars[i].is_implicit_save;
        v->pointer_associated = func->saved_vars[i].pointer_associated;
        copy_cstr(v->pointer_target, sizeof(v->pointer_target), func->saved_vars[i].pointer_target);
        v->pointer_has_slice = func->saved_vars[i].pointer_has_slice;
        v->pointer_slice_start = func->saved_vars[i].pointer_slice_start;
        v->pointer_slice_end = func->saved_vars[i].pointer_slice_end;
    }
}

static void store_saved_vars(OfortFunc *func, OfortScope *scope) {
    for (int i = 0; i < scope->n_vars; i++) {
        OfortVar *src = &scope->vars[i];
        OfortVar *dst;
        if (!src->is_save) continue;
        dst = find_saved_var(func, src->name);
        if (!dst) {
            if (func->n_saved_vars >= OFORT_MAX_VARS) continue;
            dst = &func->saved_vars[func->n_saved_vars++];
            memset(dst, 0, sizeof(*dst));
            copy_cstr(dst->name, sizeof(dst->name), src->name);
        } else {
            free_value(&dst->val);
        }
        dst->val = copy_value(src->val);
        dst->is_parameter = src->is_parameter;
        dst->intent = src->intent;
        dst->char_len = src->char_len;
        dst->present = src->present;
        dst->is_allocatable = src->is_allocatable;
        dst->is_pointer = src->is_pointer;
        dst->is_target = src->is_target;
        dst->is_protected = src->is_protected;
        dst->is_save = 1;
        dst->is_implicit_save = src->is_implicit_save;
        dst->pointer_associated = src->pointer_associated;
        copy_cstr(dst->pointer_target, sizeof(dst->pointer_target), src->pointer_target);
        dst->pointer_has_slice = src->pointer_has_slice;
        dst->pointer_slice_start = src->pointer_slice_start;
        dst->pointer_slice_end = src->pointer_slice_end;
    }
}

/* ── Type definition lookup ──────────────────── */
static OfortTypeDef *find_type_def(OfortInterpreter *I, const char *name) {
    char upper[256];
    str_upper(upper, name, 256);
    int i;
    for (i = 0; i < I->n_type_defs; i++) {
        char tu[256];
        str_upper(tu, I->type_defs[i].name, 256);
        if (strcmp(upper, tu) == 0) return &I->type_defs[i];
    }
    return NULL;
}

/* ══════════════════════════════════════════════
 *  LEXER
 * ══════════════════════════════════════════════ */

typedef struct {
    const char *keyword;
    OfortTokenType token;
} KeywordEntry;

static const KeywordEntry fortran_keywords[] = {
    {"PROGRAM", FTOK_PROGRAM}, {"END", FTOK_END},
    {"SUBROUTINE", FTOK_SUBROUTINE}, {"FUNCTION", FTOK_FUNCTION},
    {"MODULE", FTOK_MODULE}, {"USE", FTOK_USE},
    {"CONTAINS", FTOK_CONTAINS}, {"TYPE", FTOK_TYPE},
    {"IMPLICIT", FTOK_IMPLICIT}, {"NONE", FTOK_NONE},
    {"INTEGER", FTOK_INTEGER}, {"REAL", FTOK_REAL},
    {"DOUBLE", FTOK_DOUBLE_PRECISION}, /* handled specially below */
    {"CHARACTER", FTOK_CHARACTER}, {"LOGICAL", FTOK_LOGICAL},
    {"COMPLEX", FTOK_COMPLEX},
    {"IF", FTOK_IF}, {"THEN", FTOK_THEN}, {"ELSE", FTOK_ELSE},
    {"ELSEIF", FTOK_ELSEIF},
    {"DO", FTOK_DO}, {"WHILE", FTOK_WHILE},
    {"SELECT", FTOK_SELECT}, {"CASE", FTOK_CASE},
    {"DEFAULT", FTOK_DEFAULT},
    {"EXIT", FTOK_EXIT}, {"CYCLE", FTOK_CYCLE},
    {"RETURN", FTOK_RETURN}, {"STOP", FTOK_STOP},
    {"CALL", FTOK_CALL},
    {"DIMENSION", FTOK_DIMENSION}, {"ALLOCATABLE", FTOK_ALLOCATABLE},
    {"ALLOCATE", FTOK_ALLOCATE}, {"DEALLOCATE", FTOK_DEALLOCATE},
    {"PARAMETER", FTOK_PARAMETER},
    {"INTENT", FTOK_INTENT}, {"IN", FTOK_IN}, {"OUT", FTOK_OUT},
    {"INOUT", FTOK_INOUT}, {"RESULT", FTOK_RESULT},
    {"SAVE", FTOK_SAVE}, {"DATA", FTOK_DATA},
    {"PRINT", FTOK_PRINT}, {"WRITE", FTOK_WRITE}, {"READ", FTOK_READ},
    {"OPEN", FTOK_OPEN}, {"CLOSE", FTOK_CLOSE},
    {NULL, FTOK_EOF}
};

static void tokenize(OfortInterpreter *I, const char *src) {
    const char *p = src;
    int line = 1;
    I->n_tokens = 0;

    while (*p) {
        /* skip spaces and tabs (not newlines) */
        while (*p == ' ' || *p == '\t') p++;

        if (!*p) break;

        /* continuation: & at end of line */
        if (*p == '&') {
            p++;
            while (*p == ' ' || *p == '\t') p++;
            if (*p == '\n') { p++; line++; }
            /* skip leading & on next line too */
            while (*p == ' ' || *p == '\t') p++;
            if (*p == '&') p++;
            continue;
        }

        /* newline = statement separator */
        if (*p == '\n') {
            /* collapse multiple newlines */
            if (I->n_tokens > 0 && I->tokens[I->n_tokens - 1].type != FTOK_NEWLINE) {
                OfortToken *t = &I->tokens[I->n_tokens++];
                t->type = FTOK_NEWLINE;
                t->start = p;
                t->length = 1;
                t->line = line;
            }
            p++; line++;
            continue;
        }

        /* comment: ! to end of line */
        if (*p == '!') {
            while (*p && *p != '\n') p++;
            continue;
        }

        /* semicolon = statement separator */
        if (*p == ';') {
            if (I->n_tokens > 0 && I->tokens[I->n_tokens - 1].type != FTOK_NEWLINE) {
                OfortToken *t = &I->tokens[I->n_tokens++];
                t->type = FTOK_NEWLINE; /* treat as newline */
                t->start = p;
                t->length = 1;
                t->line = line;
            }
            p++;
            continue;
        }

        if (I->n_tokens >= OFORT_MAX_TOKENS - 1) ofort_error(I, "Too many tokens");

        OfortToken *t = &I->tokens[I->n_tokens];
        t->start = p;
        t->line = line;
        t->num_val = 0;
        t->int_val = 0;
        t->kind = 0;
        t->str_val[0] = '\0';

        /* dot-operators: .AND. .OR. .NOT. .EQ. .NE. .LT. .GT. .LE. .GE.
           .TRUE. .FALSE. .EQV. .NEQV. */
        if (*p == '.') {
            const char *start = p;
            p++;
            char dotword[20];
            int dlen = 0;
            while (*p && *p != '.' && dlen < 18) {
                dotword[dlen++] = (char)toupper((unsigned char)*p);
                p++;
            }
            dotword[dlen] = '\0';
            if (*p == '.') {
                p++; /* skip closing dot */
                if (strcmp(dotword, "AND") == 0) { t->type = FTOK_AND; }
                else if (strcmp(dotword, "OR") == 0) { t->type = FTOK_OR; }
                else if (strcmp(dotword, "NOT") == 0) { t->type = FTOK_NOT; }
                else if (strcmp(dotword, "EQ") == 0) { t->type = FTOK_EQ; }
                else if (strcmp(dotword, "NE") == 0) { t->type = FTOK_NEQ; }
                else if (strcmp(dotword, "LT") == 0) { t->type = FTOK_LT; }
                else if (strcmp(dotword, "GT") == 0) { t->type = FTOK_GT; }
                else if (strcmp(dotword, "LE") == 0) { t->type = FTOK_LE; }
                else if (strcmp(dotword, "GE") == 0) { t->type = FTOK_GE; }
                else if (strcmp(dotword, "TRUE") == 0) { t->type = FTOK_TRUE; }
                else if (strcmp(dotword, "FALSE") == 0) { t->type = FTOK_FALSE; }
                else if (strcmp(dotword, "EQV") == 0) { t->type = FTOK_EQVOP; }
                else if (strcmp(dotword, "NEQV") == 0) { t->type = FTOK_NEQVOP; }
                else {
                    /* Unknown dot-operator, treat as error */
                    ofort_error(I, "Unknown operator .%s. at line %d", dotword, line);
                }
                t->length = (int)(p - start);
                I->n_tokens++;
                continue;
            } else {
                /* Not a dot-operator, backtrack */
                p = start;
                /* fall through - the dot might be decimal point, but
                   digits should have caught it. Treat as percent maybe? */
                /* Actually a lone dot shouldn't appear; skip it */
                p++;
                continue;
            }
        }

        /* numbers: integer or real literal */
        if (isdigit((unsigned char)*p)) {
            const char *start = p;
            int is_real = 0;
            int is_double_lit = 0;
            int literal_kind = 0;
            while (isdigit((unsigned char)*p)) p++;
            if (*p == '.' && *(p+1) != '.') { /* avoid confusing with .. if ever */
                is_real = 1;
                p++;
                while (isdigit((unsigned char)*p)) p++;
            }
            if (*p == 'e' || *p == 'E' || *p == 'd' || *p == 'D') {
                is_real = 1;
                if (*p == 'd' || *p == 'D') is_double_lit = 1;
                p++;
                if (*p == '+' || *p == '-') p++;
                while (isdigit((unsigned char)*p)) p++;
            }
            t->length = (int)(p - start);
            if (*p == '_') {
                const char *kind_start;
                char kindbuf[32];
                int kind_len;
                p++;
                kind_start = p;
                while (isalnum((unsigned char)*p) || *p == '_') p++;
                kind_len = (int)(p - kind_start);
                if (kind_len > 0 && kind_len < (int)sizeof(kindbuf)) {
                    memcpy(kindbuf, kind_start, (size_t)kind_len);
                    kindbuf[kind_len] = '\0';
                    if (isdigit((unsigned char)kindbuf[0])) {
                        literal_kind = atoi(kindbuf);
                    }
                }
            }
            /* parse the number */
            char numbuf[128];
            int nl = t->length < 127 ? t->length : 127;
            memcpy(numbuf, start, nl);
            numbuf[nl] = '\0';
            /* replace D/d exponent with E for strtod */
            for (int k = 0; k < nl; k++) {
                if (numbuf[k] == 'd' || numbuf[k] == 'D') numbuf[k] = 'E';
            }
            if (is_real) {
                t->type = FTOK_REAL_LIT;
                t->num_val = strtod(numbuf, NULL);
                t->int_val = is_double_lit ? 1 : 0;
                t->kind = literal_kind ? literal_kind : (is_double_lit ? 8 : 4);
            } else {
                t->type = FTOK_INT_LIT;
                t->int_val = strtoll(numbuf, NULL, 10);
                t->num_val = (double)t->int_val;
                t->kind = literal_kind ? literal_kind : 4;
            }
            I->n_tokens++;
            continue;
        }

        /* strings: '...' or "..." */
        if (*p == '\'' || *p == '"') {
            char quote = *p;
            p++; /* skip opening quote */
            int slen = 0;
            while (*p && !(*p == quote && *(p+1) != quote)) {
                if (*p == quote && *(p+1) == quote) {
                    /* escaped quote */
                    t->str_val[slen++] = quote;
                    p += 2;
                } else {
                    if (*p == '\n') line++;
                    t->str_val[slen++] = *p;
                    p++;
                }
                if (slen >= OFORT_MAX_STRLEN - 1) break;
            }
            t->str_val[slen] = '\0';
            if (*p == quote) p++;
            t->type = FTOK_STRING_LIT;
            t->length = (int)(p - t->start);
            I->n_tokens++;
            continue;
        }

        /* identifiers and keywords */
        if (isalpha((unsigned char)*p) || *p == '_') {
            const char *start = p;
            while (isalnum((unsigned char)*p) || *p == '_') p++;
            int idlen = (int)(p - start);
            t->length = idlen;

            /* convert to upper for keyword matching */
            char upper[256];
            int ul = idlen < 255 ? idlen : 255;
            for (int k = 0; k < ul; k++)
                upper[k] = (char)toupper((unsigned char)start[k]);
            upper[ul] = '\0';

            /* copy original to str_val for identifiers */
            memcpy(t->str_val, start, ul);
            t->str_val[ul] = '\0';

            /* check for DOUBLE PRECISION */
            if (strcmp(upper, "DOUBLE") == 0) {
                const char *q = p;
                while (*q == ' ' || *q == '\t') q++;
                char next_word[20];
                int nwl = 0;
                while (isalpha((unsigned char)*q) && nwl < 18) {
                    next_word[nwl++] = (char)toupper((unsigned char)*q);
                    q++;
                }
                next_word[nwl] = '\0';
                if (strcmp(next_word, "PRECISION") == 0) {
                    t->type = FTOK_DOUBLE_PRECISION;
                    t->length = (int)(q - start);
                    p = q;
                    I->n_tokens++;
                    continue;
                }
            }

            /* check for ELSE IF (as single ELSEIF token) */
            if (strcmp(upper, "ELSE") == 0) {
                const char *q = p;
                while (*q == ' ' || *q == '\t') q++;
                char nw[10]; int nwl2 = 0;
                while (isalpha((unsigned char)*q) && nwl2 < 8) {
                    nw[nwl2++] = (char)toupper((unsigned char)*q);
                    q++;
                }
                nw[nwl2] = '\0';
                if (strcmp(nw, "IF") == 0) {
                    t->type = FTOK_ELSEIF;
                    t->length = (int)(q - start);
                    p = q;
                    I->n_tokens++;
                    continue;
                }
            }

            /* check for END PROGRAM, END DO, etc. — we'll let the parser handle multi-word END */
            /* keyword lookup */
            t->type = FTOK_IDENT;
            for (int k = 0; fortran_keywords[k].keyword; k++) {
                if (strcmp(upper, fortran_keywords[k].keyword) == 0) {
                    t->type = fortran_keywords[k].token;
                    break;
                }
            }
            I->n_tokens++;
            continue;
        }

        /* multi-char operators */
        if (*p == '*' && *(p+1) == '*') {
            t->type = FTOK_POWER; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '/' && *(p+1) == '/') {
            t->type = FTOK_CONCAT; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '/' && *(p+1) == '=') {
            t->type = FTOK_NEQ; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '=' && *(p+1) == '=') {
            t->type = FTOK_EQ; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '=' && *(p+1) == '>') {
            t->type = FTOK_POINTER_ASSIGN; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '<' && *(p+1) == '=') {
            t->type = FTOK_LE; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '>' && *(p+1) == '=') {
            t->type = FTOK_GE; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == ':' && *(p+1) == ':') {
            t->type = FTOK_DCOLON; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '_' && (isdigit((unsigned char)*(p+1)) || isalpha((unsigned char)*(p+1)))) {
            p++;
            while (isalnum((unsigned char)*p) || *p == '_') p++;
            continue;
        }
        /* array constructor (/ ... /) — bracket form */
        if (*p == '(' && *(p+1) == '/') {
            t->type = FTOK_LBRACKET; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }
        if (*p == '/' && *(p+1) == ')') {
            t->type = FTOK_RBRACKET; t->length = 2; p += 2;
            I->n_tokens++; continue;
        }

        /* single-char */
        switch (*p) {
            case '+': t->type = FTOK_PLUS; break;
            case '-': t->type = FTOK_MINUS; break;
            case '*': t->type = FTOK_STAR; break;
            case '/': t->type = FTOK_SLASH; break;
            case '=': t->type = FTOK_ASSIGN; break;
            case '<': t->type = FTOK_LT; break;
            case '>': t->type = FTOK_GT; break;
            case '(': t->type = FTOK_LPAREN; break;
            case ')': t->type = FTOK_RPAREN; break;
            case '[': t->type = FTOK_LBRACKET; break;
            case ']': t->type = FTOK_RBRACKET; break;
            case ',': t->type = FTOK_COMMA; break;
            case ':': t->type = FTOK_COLON; break;
            case '%': t->type = FTOK_PERCENT; break;
            default:
                ofort_error(I, "Unexpected character '%c' (0x%02x) at line %d", *p, (unsigned char)*p, line);
        }
        t->length = 1;
        p++;
        I->n_tokens++;
    }

    /* final EOF */
    OfortToken *t = &I->tokens[I->n_tokens++];
    t->type = FTOK_EOF;
    t->start = p;
    t->length = 0;
    t->line = line;
}

/* ══════════════════════════════════════════════
 *  PARSER
 * ══════════════════════════════════════════════ */

static OfortToken *peek(OfortInterpreter *I) {
    return &I->tokens[I->tok_pos];
}

static OfortToken *peek_ahead(OfortInterpreter *I, int offset) {
    int pos = I->tok_pos + offset;
    if (pos >= I->n_tokens) pos = I->n_tokens - 1;
    return &I->tokens[pos];
}

static OfortToken *advance(OfortInterpreter *I) {
    OfortToken *t = &I->tokens[I->tok_pos];
    if (t->type != FTOK_EOF) I->tok_pos++;
    return t;
}

static int check(OfortInterpreter *I, OfortTokenType type) {
    return peek(I)->type == type;
}

static OfortToken *expect(OfortInterpreter *I, OfortTokenType type) {
    OfortToken *t = peek(I);
    if (t->type != type) {
        ofort_error(I, "Expected token type %d, got %d at line %d", type, t->type, t->line);
    }
    return advance(I);
}

static void skip_newlines(OfortInterpreter *I) {
    while (peek(I)->type == FTOK_NEWLINE) advance(I);
}

static int check_ident_upper(OfortInterpreter *I, const char *name) {
    OfortToken *t = peek(I);
    if (t->type != FTOK_IDENT) return 0;
    char upper[256];
    str_upper(upper, t->str_val, 256);
    return strcmp(upper, name) == 0;
}

static int token_ident_upper(OfortToken *t, const char *name) {
    char upper[256];
    if (!t || t->type != FTOK_IDENT) return 0;
    str_upper(upper, t->str_val, 256);
    return strcmp(upper, name) == 0;
}

static void skip_to_next_line(OfortInterpreter *I) {
    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        advance(I);
    }
    skip_newlines(I);
}

static int check_end_ident(OfortInterpreter *I, const char *name) {
    return peek(I)->type == FTOK_END && token_ident_upper(peek_ahead(I, 1), name);
}

static const char *token_arg_name(OfortToken *t) {
    if (!t) return NULL;
    if (t->type == FTOK_IDENT) return t->str_val;
    if (t->type == FTOK_DIMENSION) return "dim";
    if (t->type == FTOK_INTENT) return "intent";
    if (t->type == FTOK_RESULT) return "result";
    if (t->type == FTOK_ALLOCATABLE) return "allocatable";
    if (t->type == FTOK_IN || t->type == FTOK_OUT || t->type == FTOK_INOUT) return NULL;
    return NULL;
}

static int check_keyword_arg(OfortInterpreter *I) {
    return token_arg_name(peek(I)) != NULL && peek_ahead(I, 1)->type == FTOK_ASSIGN;
}

static void skip_interface_block(OfortInterpreter *I) {
    advance(I); /* INTERFACE */
    skip_to_next_line(I);
    while (!check(I, FTOK_EOF)) {
        if (check_end_ident(I, "INTERFACE")) {
            advance(I); /* END */
            advance(I); /* INTERFACE */
            if (check(I, FTOK_IDENT)) advance(I); /* optional generic name */
            skip_newlines(I);
            return;
        }
        advance(I);
    }
}

/* Check if current token is END followed by a keyword (END PROGRAM, END DO, etc.) */
static int check_end(OfortInterpreter *I, const char *what) {
    if (peek(I)->type != FTOK_END) return 0;
    if (!what) return 1;
    OfortToken *next = peek_ahead(I, 1);
    if (next->type == FTOK_NEWLINE || next->type == FTOK_EOF) return 1;
    char upper[256];
    if (next->type == FTOK_IDENT) {
        str_upper(upper, next->str_val, 256);
    } else {
        /* map token type to string */
        switch (next->type) {
            case FTOK_PROGRAM: strcpy(upper, "PROGRAM"); break;
            case FTOK_DO: strcpy(upper, "DO"); break;
            case FTOK_IF: strcpy(upper, "IF"); break;
            case FTOK_SELECT: strcpy(upper, "SELECT"); break;
            case FTOK_SUBROUTINE: strcpy(upper, "SUBROUTINE"); break;
            case FTOK_FUNCTION: strcpy(upper, "FUNCTION"); break;
            case FTOK_MODULE: strcpy(upper, "MODULE"); break;
            case FTOK_TYPE: strcpy(upper, "TYPE"); break;
            default: return 0;
        }
    }
    char wup[256];
    str_upper(wup, what, 256);
    return strcmp(upper, wup) == 0;
}

static void consume_end(OfortInterpreter *I, const char *what) {
    expect(I, FTOK_END);
    if (what) {
        OfortToken *t = peek(I);
        /* consume the keyword after END if present */
        if (t->type != FTOK_NEWLINE && t->type != FTOK_EOF) {
            advance(I); /* skip PROGRAM/DO/IF/etc. */
            /* optionally skip name after END PROGRAM name */
            if (peek(I)->type == FTOK_IDENT) advance(I);
        }
    }
}

/* ── Expression parsing (precedence climbing) ── */
static OfortNode *parse_expr(OfortInterpreter *I);
static OfortNode *parse_statement(OfortInterpreter *I);

static OfortNode *parse_primary(OfortInterpreter *I) {
    OfortToken *t = peek(I);

    /* integer literal */
    if (t->type == FTOK_INT_LIT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_INT_LIT);
        n->int_val = t->int_val;
        n->num_val = t->num_val;
        n->kind = t->kind;
        n->line = t->line;
        return n;
    }
    /* real literal */
    if (t->type == FTOK_REAL_LIT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_REAL_LIT);
        n->num_val = t->num_val;
        n->kind = t->kind;
        n->val_type = FVAL_REAL;
        if (t->kind == 8) n->val_type = FVAL_DOUBLE;
        for (int k = 0; k < t->length; k++) {
            if (t->start[k] == 'd' || t->start[k] == 'D') {
                n->val_type = FVAL_DOUBLE;
                break;
            }
        }
        n->line = t->line;
        return n;
    }
    /* string literal */
    if (t->type == FTOK_STRING_LIT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_STRING_LIT);
        copy_cstr(n->str_val, sizeof(n->str_val), t->str_val);
        n->line = t->line;
        return n;
    }
    /* logical literals */
    if (t->type == FTOK_TRUE) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_LOGICAL_LIT);
        n->bool_val = 1; n->line = t->line;
        return n;
    }
    if (t->type == FTOK_FALSE) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_LOGICAL_LIT);
        n->bool_val = 0; n->line = t->line;
        return n;
    }
    /* .NOT. (unary) */
    if (t->type == FTOK_NOT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_NOT);
        n->children[0] = parse_primary(I);
        n->n_children = 1;
        n->line = t->line;
        return n;
    }
    /* parenthesized expr or complex literal (re, im) */
    if (t->type == FTOK_LPAREN) {
        advance(I);
        OfortNode *first = parse_expr(I);
        if (check(I, FTOK_COMMA)) {
            /* complex literal: (real, imag) */
            advance(I);
            OfortNode *second = parse_expr(I);
            expect(I, FTOK_RPAREN);
            OfortNode *n = alloc_node(I, FND_COMPLEX_LIT);
            n->children[0] = first;
            n->children[1] = second;
            n->n_children = 2;
            n->line = t->line;
            return n;
        }
        expect(I, FTOK_RPAREN);
        return first;
    }
    /* array constructor [a, b, c] or (/ a, b, c /) */
    if (t->type == FTOK_LBRACKET) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_ARRAY_CONSTRUCTOR);
        n->line = t->line;
        n->stmts = NULL;
        n->n_stmts = 0;
        int cap = 0;
        if (peek(I)->type == FTOK_INTEGER || peek(I)->type == FTOK_REAL ||
            peek(I)->type == FTOK_DOUBLE_PRECISION || peek(I)->type == FTOK_CHARACTER ||
            peek(I)->type == FTOK_LOGICAL || peek(I)->type == FTOK_COMPLEX) {
            while (!check(I, FTOK_DCOLON) && !check(I, FTOK_RBRACKET) && !check(I, FTOK_EOF)) {
                advance(I);
            }
            if (check(I, FTOK_DCOLON)) advance(I);
        }
        while (!check(I, FTOK_RBRACKET) && !check(I, FTOK_EOF)) {
            OfortNode *elem = parse_expr(I);
            if (n->n_stmts >= cap) {
                cap = cap ? cap * 2 : 8;
                n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
            }
            n->stmts[n->n_stmts++] = elem;
            if (check(I, FTOK_COMMA)) advance(I);
        }
        expect(I, FTOK_RBRACKET);
        return n;
    }
    /* unary minus */
    if (t->type == FTOK_MINUS) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_NEGATE);
        n->children[0] = parse_primary(I);
        n->n_children = 1;
        n->line = t->line;
        return n;
    }
    /* unary plus */
    if (t->type == FTOK_PLUS) {
        advance(I);
        return parse_primary(I);
    }
    /* identifier — could be variable, function call, or array ref */
    if (type_token_intrinsic_name(t->type) && peek_ahead(I, 1)->type == FTOK_LPAREN) {
        const char *intrinsic_name = type_token_intrinsic_name(t->type);
        advance(I);
        OfortNode *n = alloc_node(I, FND_IDENT);
        copy_cstr(n->name, sizeof(n->name), intrinsic_name);
        n->line = t->line;

        while (check(I, FTOK_LPAREN)) {
            advance(I);
            OfortNode *call_node = alloc_node(I, FND_FUNC_CALL);
            copy_cstr(call_node->name, sizeof(call_node->name), n->name);
            call_node->line = n->line;
            call_node->stmts = NULL;
            call_node->n_stmts = 0;
            int cap2 = 0;

            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                const char *arg_name = NULL;
                if (check_keyword_arg(I)) {
                    arg_name = token_arg_name(advance(I));
                    advance(I); /* = */
                }
                OfortNode *arg = parse_expr(I);
                if (call_node->n_stmts >= cap2) {
                    cap2 = cap2 ? cap2 * 2 : 8;
                    call_node->stmts = (OfortNode **)realloc(call_node->stmts, sizeof(OfortNode *) * cap2);
                }
                if (arg_name) copy_cstr(call_node->param_names[call_node->n_stmts], sizeof(call_node->param_names[call_node->n_stmts]), arg_name);
                call_node->stmts[call_node->n_stmts++] = arg;
                if (check(I, FTOK_COMMA)) advance(I);
            }
            expect(I, FTOK_RPAREN);
            n = call_node;
        }

        return n;
    }
    if (t->type == FTOK_IDENT || t->type == FTOK_IN || t->type == FTOK_OUT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_IDENT);
        if (t->type == FTOK_IN) copy_cstr(n->name, sizeof(n->name), "in");
        else if (t->type == FTOK_OUT) copy_cstr(n->name, sizeof(n->name), "out");
        else copy_cstr(n->name, sizeof(n->name), t->str_val);
        n->line = t->line;

        /* function call / array reference: ident( ... ) */
        while (check(I, FTOK_LPAREN)) {
            advance(I);
            /* check if this is a slice: ident(start:end) */
            /* Parse argument list */
            OfortNode *call_node;
            /* determine if function call or array ref later at eval time */
            call_node = alloc_node(I, FND_FUNC_CALL);
            copy_cstr(call_node->name, sizeof(call_node->name), n->name);
            call_node->line = n->line;
            call_node->stmts = NULL;
            call_node->n_stmts = 0;
            int cap2 = 0;

            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                const char *arg_name = NULL;
                if (check_keyword_arg(I)) {
                    arg_name = token_arg_name(advance(I));
                    advance(I); /* = */
                }
                /* Check for slice notation: expr:expr, :expr, expr:, or : */
                OfortNode *arg = NULL;
                if (check(I, FTOK_DCOLON)) {
                    OfortNode *slice = alloc_node(I, FND_SLICE);
                    slice->children[0] = NULL;
                    slice->children[1] = NULL;
                    slice->n_children = 2;
                    advance(I);
                    if (!check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA)) {
                        slice->children[2] = parse_expr(I);
                        slice->n_children = 3;
                    }
                    arg = slice;
                } else if (check(I, FTOK_COLON)) {
                    OfortNode *slice = alloc_node(I, FND_SLICE);
                    slice->children[0] = NULL;
                    slice->n_children = 2;
                    advance(I);
                    if (!check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA) && !check(I, FTOK_COLON)) {
                        slice->children[1] = parse_expr(I);
                    } else {
                        slice->children[1] = NULL;
                    }
                    if (check(I, FTOK_COLON)) {
                        advance(I);
                        if (!check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA)) {
                            slice->children[2] = parse_expr(I);
                            slice->n_children = 3;
                        }
                    }
                    arg = slice;
                } else {
                    arg = parse_expr(I);
                }
                if (arg && arg->type != FND_SLICE && (check(I, FTOK_COLON) || check(I, FTOK_DCOLON))) {
                    int double_colon = check(I, FTOK_DCOLON);
                    advance(I);
                    OfortNode *slice = alloc_node(I, FND_SLICE);
                    slice->children[0] = arg;
                    slice->n_children = 2;
                    if (!double_colon && !check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA) && !check(I, FTOK_COLON)) {
                        slice->children[1] = parse_expr(I);
                    } else {
                        slice->children[1] = NULL; /* open-ended slice */
                    }
                    /* optional stride: start:end:stride */
                    if (double_colon || check(I, FTOK_COLON)) {
                        if (!double_colon) advance(I);
                        if (!check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA)) {
                            slice->children[2] = parse_expr(I);
                            slice->n_children = 3;
                        }
                    }
                    arg = slice;
                }
                if (call_node->n_stmts >= cap2) {
                    cap2 = cap2 ? cap2 * 2 : 8;
                    call_node->stmts = (OfortNode **)realloc(call_node->stmts, sizeof(OfortNode *) * cap2);
                }
                if (arg_name) copy_cstr(call_node->param_names[call_node->n_stmts], sizeof(call_node->param_names[call_node->n_stmts]), arg_name);
                call_node->stmts[call_node->n_stmts++] = arg;
                if (check(I, FTOK_COMMA)) advance(I);
            }
            expect(I, FTOK_RPAREN);
            n = call_node;
        }

        /* member access: ident%member */
        while (check(I, FTOK_PERCENT)) {
            advance(I);
            OfortToken *mt = expect(I, FTOK_IDENT);
            OfortNode *mem = alloc_node(I, FND_MEMBER);
            mem->children[0] = n;
            copy_cstr(mem->name, sizeof(mem->name), mt->str_val);
            mem->n_children = 1;
            mem->line = mt->line;
            n = mem;
        }

        return n;
    }

    ofort_error(I, "Unexpected token at line %d (type %d)", t->line, t->type);
    return NULL; /* unreachable */
}

/* operator precedence levels */
static OfortNode *parse_power(OfortInterpreter *I) {
    OfortNode *left = parse_primary(I);
    while (check(I, FTOK_POWER)) {
        advance(I);
        OfortNode *right = parse_primary(I); /* right-associative */
        OfortNode *n = alloc_node(I, FND_POWER);
        n->children[0] = left;
        n->children[1] = right;
        n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_unary(OfortInterpreter *I) {
    return parse_power(I);
}

static OfortNode *parse_mul(OfortInterpreter *I) {
    OfortNode *left = parse_unary(I);
    while (check(I, FTOK_STAR) || check(I, FTOK_SLASH)) {
        OfortTokenType op = advance(I)->type;
        OfortNode *right = parse_unary(I);
        OfortNode *n = alloc_node(I, op == FTOK_STAR ? FND_MUL : FND_DIV);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_add(OfortInterpreter *I) {
    OfortNode *left = parse_mul(I);
    while (check(I, FTOK_PLUS) || check(I, FTOK_MINUS)) {
        OfortTokenType op = advance(I)->type;
        OfortNode *right = parse_mul(I);
        OfortNode *n = alloc_node(I, op == FTOK_PLUS ? FND_ADD : FND_SUB);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_concat(OfortInterpreter *I) {
    OfortNode *left = parse_add(I);
    while (check(I, FTOK_CONCAT)) {
        advance(I);
        OfortNode *right = parse_add(I);
        OfortNode *n = alloc_node(I, FND_CONCAT);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_comparison(OfortInterpreter *I) {
    OfortNode *left = parse_concat(I);
    while (check(I, FTOK_EQ) || check(I, FTOK_NEQ) ||
           check(I, FTOK_LT) || check(I, FTOK_GT) ||
           check(I, FTOK_LE) || check(I, FTOK_GE)) {
        OfortTokenType op = advance(I)->type;
        OfortNode *right = parse_concat(I);
        OfortNodeType nt;
        switch (op) {
            case FTOK_EQ: nt = FND_EQ; break;
            case FTOK_NEQ: nt = FND_NEQ; break;
            case FTOK_LT: nt = FND_LT; break;
            case FTOK_GT: nt = FND_GT; break;
            case FTOK_LE: nt = FND_LE; break;
            case FTOK_GE: nt = FND_GE; break;
            default: nt = FND_EQ; break;
        }
        OfortNode *n = alloc_node(I, nt);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_not(OfortInterpreter *I) {
    if (check(I, FTOK_NOT)) {
        OfortToken *t = advance(I);
        OfortNode *n = alloc_node(I, FND_NOT);
        n->children[0] = parse_comparison(I);
        n->n_children = 1;
        n->line = t->line;
        return n;
    }
    return parse_comparison(I);
}

static OfortNode *parse_and(OfortInterpreter *I) {
    OfortNode *left = parse_not(I);
    while (check(I, FTOK_AND)) {
        advance(I);
        OfortNode *right = parse_not(I);
        OfortNode *n = alloc_node(I, FND_AND);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_or(OfortInterpreter *I) {
    OfortNode *left = parse_and(I);
    while (check(I, FTOK_OR)) {
        advance(I);
        OfortNode *right = parse_and(I);
        OfortNode *n = alloc_node(I, FND_OR);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_eqv(OfortInterpreter *I) {
    OfortNode *left = parse_or(I);
    while (check(I, FTOK_EQVOP) || check(I, FTOK_NEQVOP)) {
        OfortTokenType op = advance(I)->type;
        OfortNode *right = parse_or(I);
        OfortNode *n = alloc_node(I, op == FTOK_EQVOP ? FND_EQV : FND_NEQV);
        n->children[0] = left; n->children[1] = right; n->n_children = 2;
        n->line = left->line;
        left = n;
    }
    return left;
}

static OfortNode *parse_expr(OfortInterpreter *I) {
    return parse_eqv(I);
}

/* ── Type keyword checking ──────────────────── */
static int is_type_keyword(OfortTokenType t) {
    return t == FTOK_INTEGER || t == FTOK_REAL || t == FTOK_DOUBLE_PRECISION ||
           t == FTOK_CHARACTER || t == FTOK_LOGICAL || t == FTOK_COMPLEX;
}

static OfortValType token_to_valtype(OfortTokenType t) {
    switch (t) {
        case FTOK_INTEGER: return FVAL_INTEGER;
        case FTOK_REAL: return FVAL_REAL;
        case FTOK_DOUBLE_PRECISION: return FVAL_DOUBLE;
        case FTOK_CHARACTER: return FVAL_CHARACTER;
        case FTOK_LOGICAL: return FVAL_LOGICAL;
        case FTOK_COMPLEX: return FVAL_COMPLEX;
        default: return FVAL_INTEGER;
    }
}

/* ── Declaration parsing ────────────────────── */
static OfortNode *parse_declaration(OfortInterpreter *I) {
    OfortToken *type_tok = advance(I); /* consume type keyword */
    OfortValType vtype = token_to_valtype(type_tok->type);
    int char_len = 1;
    OfortNode *char_len_expr = NULL;
    int is_allocatable = 0;
    int is_pointer = 0;
    int is_target = 0;
    int is_protected = 0;
    int is_save = 0;
    int is_implicit_save = 0;
    int is_parameter = 0;
    int is_optional = 0;
    int intent = 0;
    int decl_dims[7] = {0};
    int n_decl_dims = 0;

    /* optional (LEN=n) or (KIND=n) for CHARACTER */
    if (vtype == FVAL_CHARACTER && check(I, FTOK_LPAREN)) {
        advance(I);
        /* CHARACTER(LEN=20) or CHARACTER(20) */
        if (check_ident_upper(I, "LEN")) {
            advance(I); /* LEN */
            expect(I, FTOK_ASSIGN); /* = */
            if (check(I, FTOK_STAR)) {
                advance(I);
                char_len = OFORT_MAX_STRLEN - 1;
            } else {
                char_len_expr = parse_expr(I);
                if (char_len_expr->type == FND_INT_LIT)
                    char_len = (int)char_len_expr->int_val;
            }
        } else if (check(I, FTOK_STAR)) {
            advance(I);
            char_len = OFORT_MAX_STRLEN - 1;
        } else if (check(I, FTOK_INT_LIT)) {
            char_len = (int)peek(I)->int_val;
            advance(I);
        }
        expect(I, FTOK_RPAREN);
    }

    /* optional KIND for integer/real: INTEGER(KIND=4) or INTEGER(4) */
    if ((vtype == FVAL_INTEGER || vtype == FVAL_REAL || vtype == FVAL_DOUBLE) && check(I, FTOK_LPAREN)) {
        advance(I);
        /* skip kind specification */
        int depth = 1;
        while (depth > 0 && !check(I, FTOK_EOF)) {
            if (check(I, FTOK_LPAREN)) depth++;
            if (check(I, FTOK_RPAREN)) depth--;
            if (depth > 0) advance(I);
        }
        if (check(I, FTOK_RPAREN)) advance(I);
    }

    /* optional attributes before :: */
    while (check(I, FTOK_COMMA)) {
        advance(I);
        if (check(I, FTOK_DIMENSION)) {
            advance(I);
            expect(I, FTOK_LPAREN);
            /* parse dimension spec */
            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                if (check(I, FTOK_COLON)) {
                    /* allocatable dimension (:) */
                    advance(I);
                    decl_dims[n_decl_dims++] = 0; /* unknown size */
                } else {
                    OfortNode *dim_expr = parse_expr(I);
                    /* For now assume it's a simple integer */
                    if (dim_expr->type == FND_INT_LIT)
                        decl_dims[n_decl_dims++] = (int)dim_expr->int_val;
                    else
                        decl_dims[n_decl_dims++] = 0;
                    /* range: skip lo:hi */
                    if (check(I, FTOK_COLON)) {
                        advance(I);
                        OfortNode *hi = parse_expr(I);
                        if (hi->type == FND_INT_LIT)
                            decl_dims[n_decl_dims - 1] = (int)hi->int_val;
                    }
                }
                if (check(I, FTOK_COMMA)) advance(I);
                else break;
            }
            expect(I, FTOK_RPAREN);
        } else if (check(I, FTOK_ALLOCATABLE)) {
            advance(I);
            is_allocatable = 1;
        } else if (check(I, FTOK_IDENT) && str_eq_nocase(peek(I)->str_val, "pointer")) {
            advance(I);
            is_pointer = 1;
        } else if (check(I, FTOK_IDENT) && str_eq_nocase(peek(I)->str_val, "target")) {
            advance(I);
            is_target = 1;
        } else if (check(I, FTOK_IDENT) && str_eq_nocase(peek(I)->str_val, "protected")) {
            advance(I);
            is_protected = 1;
        } else if (check(I, FTOK_PARAMETER)) {
            advance(I);
            is_parameter = 1;
        } else if (check(I, FTOK_IDENT) && str_eq_nocase(peek(I)->str_val, "optional")) {
            advance(I);
            is_optional = 1;
        } else if (check(I, FTOK_INTENT)) {
            advance(I);
            expect(I, FTOK_LPAREN);
            if (check(I, FTOK_IN)) { advance(I); intent = 1; }
            else if (check(I, FTOK_OUT)) { advance(I); intent = 2; }
            else if (check(I, FTOK_INOUT)) { advance(I); intent = 3; }
            if (intent == 1 && check(I, FTOK_OUT)) { advance(I); intent = 3; }
            expect(I, FTOK_RPAREN);
        } else if (check(I, FTOK_SAVE)) {
            advance(I);
            is_save = 1;
        } else {
            /* unknown attribute, skip */
            advance(I);
        }
    }

    /* optional :: */
    if (check(I, FTOK_DCOLON)) advance(I);

    /* parse variable list */
    OfortNode *block = alloc_node(I, FND_BLOCK);
    block->stmts = NULL;
    block->n_stmts = 0;
    block->line = type_tok->line;
    int cap = 0;

    do {
        OfortToken *name_tok = expect(I, FTOK_IDENT);
        OfortNode *decl = alloc_node(I, is_parameter ? FND_PARAMDECL : FND_VARDECL);
        copy_cstr(decl->name, sizeof(decl->name), name_tok->str_val);
        decl->val_type = vtype;
        decl->char_len = char_len;
        decl->char_len_expr = char_len_expr;
        decl->is_allocatable = is_allocatable;
        decl->is_pointer = is_pointer;
        decl->is_target = is_target;
        decl->is_protected = is_protected;
        decl->is_save = is_save;
        decl->is_implicit_save = is_implicit_save;
        decl->is_parameter = is_parameter;
        decl->is_optional = is_optional;
        decl->intent = intent;
        decl->line = name_tok->line;

        if (vtype == FVAL_CHARACTER && check(I, FTOK_STAR)) {
            advance(I);
            if (check(I, FTOK_LPAREN)) {
                advance(I);
                decl->char_len_expr = parse_expr(I);
                if (decl->char_len_expr->type == FND_INT_LIT)
                    decl->char_len = (int)decl->char_len_expr->int_val;
                expect(I, FTOK_RPAREN);
            } else {
                OfortToken *len_tok = expect(I, FTOK_INT_LIT);
                decl->char_len = (int)len_tok->int_val;
                decl->char_len_expr = NULL;
            }
        }

        /* copy dimension info */
        memcpy(decl->dims, decl_dims, sizeof(decl_dims));
        decl->n_dims = n_decl_dims;

        /* per-variable dimension: x(10) */
        if (check(I, FTOK_LPAREN) && n_decl_dims == 0) {
            advance(I);
            decl->n_dims = 0;
            int dim_cap = 0;
            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                if (check(I, FTOK_COLON)) {
                    advance(I);
                    decl->dims[decl->n_dims++] = 0;
                } else {
                    OfortNode *de = parse_expr(I);
                    int dim_index = decl->n_dims;
                    if (de->type == FND_INT_LIT)
                        decl->dims[decl->n_dims++] = (int)de->int_val;
                    else
                        decl->dims[decl->n_dims++] = 0;
                    if (decl->n_stmts >= dim_cap) {
                        dim_cap = dim_cap ? dim_cap * 2 : 4;
                        decl->stmts = (OfortNode **)realloc(decl->stmts, sizeof(OfortNode *) * dim_cap);
                    }
                    decl->stmts[decl->n_stmts++] = de;
                    if (check(I, FTOK_COLON)) {
                        advance(I);
                        OfortNode *dh = parse_expr(I);
                        if (dh->type == FND_INT_LIT) {
                            decl->dims[dim_index] = (int)dh->int_val;
                        } else if (dim_index < decl->n_stmts) {
                            decl->stmts[dim_index] = dh;
                        }
                    }
                }
                if (check(I, FTOK_COMMA)) advance(I);
                else break;
            }
            expect(I, FTOK_RPAREN);
        }

        /* optional initialization: = expr */
        if (check(I, FTOK_ASSIGN)) {
            advance(I);
            decl->children[0] = parse_expr(I);
            decl->n_children = 1;
            if (!decl->is_save && decl->type == FND_VARDECL) {
                decl->is_implicit_save = 1;
            }
        }

        if (block->n_stmts >= cap) {
            cap = cap ? cap * 2 : 4;
            block->stmts = (OfortNode **)realloc(block->stmts, sizeof(OfortNode *) * cap);
        }
        block->stmts[block->n_stmts++] = decl;

        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    } while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF));

    return block;
}

/* ── Statement parsing ──────────────────────── */
static OfortNode *parse_block_until_end(OfortInterpreter *I, const char *end_keyword);

static OfortNode *parse_if(OfortInterpreter *I) {
    OfortToken *ift = advance(I); /* consume IF */
    expect(I, FTOK_LPAREN);
    OfortNode *cond = parse_expr(I);
    expect(I, FTOK_RPAREN);

    OfortNode *n = alloc_node(I, FND_IF);
    n->line = ift->line;
    n->children[0] = cond;

    /* check for single-line IF (no THEN) */
    if (!check(I, FTOK_THEN)) {
        /* single line: IF (cond) statement */
        n->children[1] = parse_statement(I);
        n->n_children = 2;
        return n;
    }

    advance(I); /* consume THEN */
    skip_newlines(I);

    /* parse body until ELSE, ELSEIF, or END IF */
    OfortNode *body = alloc_node(I, FND_BLOCK);
    body->stmts = NULL; body->n_stmts = 0;
    int cap = 0;
    while (!check_end(I, "IF") && peek(I)->type != FTOK_ELSE &&
           peek(I)->type != FTOK_ELSEIF && peek(I)->type != FTOK_EOF) {
        skip_newlines(I);
        if (check_end(I, "IF") || check(I, FTOK_ELSE) || check(I, FTOK_ELSEIF)) break;
        OfortNode *s = parse_statement(I);
        if (s) {
            if (body->n_stmts >= cap) {
                cap = cap ? cap * 2 : 8;
                body->stmts = (OfortNode **)realloc(body->stmts, sizeof(OfortNode *) * cap);
            }
            body->stmts[body->n_stmts++] = s;
        }
        skip_newlines(I);
    }
    n->children[1] = body;
    n->n_children = 2;

    /* ELSE IF / ELSE */
    if (check(I, FTOK_ELSEIF)) {
        n->children[2] = parse_if(I); /* recursive: ELSE IF becomes nested IF */
        n->n_children = 3;
    } else if (check(I, FTOK_ELSE)) {
        advance(I);
        skip_newlines(I);
        OfortNode *else_body = alloc_node(I, FND_BLOCK);
        else_body->stmts = NULL; else_body->n_stmts = 0;
        int ecap = 0;
        while (!check_end(I, "IF") && peek(I)->type != FTOK_EOF) {
            skip_newlines(I);
            if (check_end(I, "IF")) break;
            OfortNode *s = parse_statement(I);
            if (s) {
                if (else_body->n_stmts >= ecap) {
                    ecap = ecap ? ecap * 2 : 8;
                    else_body->stmts = (OfortNode **)realloc(else_body->stmts, sizeof(OfortNode *) * ecap);
                }
                else_body->stmts[ecap > 0 ? else_body->n_stmts : 0] = s;
                else_body->n_stmts++;
            }
            skip_newlines(I);
        }
        n->children[2] = else_body;
        n->n_children = 3;
    }

    if (check_end(I, "IF")) {
        consume_end(I, "IF");
    }

    return n;
}

static OfortNode *parse_do(OfortInterpreter *I) {
    OfortToken *dot = advance(I); /* consume DO */

    /* DO WHILE */
    if (check(I, FTOK_WHILE)) {
        advance(I);
        expect(I, FTOK_LPAREN);
        OfortNode *cond = parse_expr(I);
        expect(I, FTOK_RPAREN);
        skip_newlines(I);

        OfortNode *n = alloc_node(I, FND_DO_WHILE);
        n->children[0] = cond;
        n->line = dot->line;

        OfortNode *body = parse_block_until_end(I, "DO");
        n->children[1] = body;
        n->n_children = 2;
        consume_end(I, "DO");
        return n;
    }

    /* DO forever, terminated by EXIT or END DO */
    if (check(I, FTOK_NEWLINE) || check(I, FTOK_SEMICOLON)) {
        OfortNode *n = alloc_node(I, FND_DO_FOREVER);
        n->line = dot->line;
        skip_newlines(I);
        OfortNode *body = parse_block_until_end(I, "DO");
        n->children[0] = body;
        n->n_children = 1;
        consume_end(I, "DO");
        return n;
    }

    /* DO i = start, end [, step] */
    OfortNode *n = alloc_node(I, FND_DO_LOOP);
    n->line = dot->line;

    /* loop variable */
    OfortToken *var_tok = expect(I, FTOK_IDENT);
    copy_cstr(n->name, sizeof(n->name), var_tok->str_val);
    expect(I, FTOK_ASSIGN);
    n->children[0] = parse_expr(I); /* start */
    expect(I, FTOK_COMMA);
    n->children[1] = parse_expr(I); /* end */
    n->n_children = 3;
    if (check(I, FTOK_COMMA)) {
        advance(I);
        n->children[2] = parse_expr(I); /* step */
    } else {
        /* default step = 1 */
        OfortNode *one = alloc_node(I, FND_INT_LIT);
        one->int_val = 1; one->num_val = 1.0;
        n->children[2] = one;
    }
    skip_newlines(I);

    OfortNode *body = parse_block_until_end(I, "DO");
    n->children[3] = body;
    n->n_children = 4;
    consume_end(I, "DO");
    return n;
}

static OfortNode *parse_select_case(OfortInterpreter *I) {
    OfortToken *st = advance(I); /* SELECT */
    expect(I, FTOK_CASE);
    expect(I, FTOK_LPAREN);
    OfortNode *expr = parse_expr(I);
    expect(I, FTOK_RPAREN);
    skip_newlines(I);

    OfortNode *n = alloc_node(I, FND_SELECT_CASE);
    n->children[0] = expr;
    n->n_children = 1;
    n->line = st->line;
    n->stmts = NULL;
    n->n_stmts = 0;
    int cap = 0;

    while (!check_end(I, "SELECT") && !check(I, FTOK_EOF)) {
        skip_newlines(I);
        if (check_end(I, "SELECT")) break;
        if (check(I, FTOK_CASE)) {
            advance(I);
            OfortNode *cb = alloc_node(I, FND_CASE_BLOCK);
            cb->line = peek(I)->line;

            if (check(I, FTOK_DEFAULT) || check_ident_upper(I, "DEFAULT")) {
                advance(I);
                cb->children[0] = NULL; /* default case */
            } else {
                expect(I, FTOK_LPAREN);
                cb->children[0] = parse_expr(I);
                /* check for range: case (lo:hi) */
                if (check(I, FTOK_COLON)) {
                    advance(I);
                    cb->children[1] = parse_expr(I);
                    cb->n_children = 2;
                }
                expect(I, FTOK_RPAREN);
            }
            skip_newlines(I);

            /* parse case body until next CASE or END SELECT */
            OfortNode *body = alloc_node(I, FND_BLOCK);
            body->stmts = NULL; body->n_stmts = 0;
            int bcap = 0;
            while (!check(I, FTOK_CASE) && !check_end(I, "SELECT") && !check(I, FTOK_EOF)) {
                skip_newlines(I);
                if (check(I, FTOK_CASE) || check_end(I, "SELECT")) break;
                OfortNode *s = parse_statement(I);
                if (s) {
                    if (body->n_stmts >= bcap) {
                        bcap = bcap ? bcap * 2 : 8;
                        body->stmts = (OfortNode **)realloc(body->stmts, sizeof(OfortNode *) * bcap);
                    }
                    body->stmts[body->n_stmts++] = s;
                }
                skip_newlines(I);
            }
            if (cb->n_children < 1) cb->n_children = 1;
            cb->children[cb->n_children] = body;
            cb->n_children++;

            if (n->n_stmts >= cap) {
                cap = cap ? cap * 2 : 8;
                n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
            }
            n->stmts[n->n_stmts++] = cb;
        } else {
            advance(I); /* skip unexpected tokens */
        }
    }
    consume_end(I, "SELECT");
    /* skip optional CASE after END SELECT (i.e. END SELECT) -- already consumed */
    return n;
}

static OfortNode *parse_io_item(OfortInterpreter *I);

static int paren_item_has_top_level_comma(OfortInterpreter *I) {
    int depth = 0;
    for (int pos = I->tok_pos; pos < I->n_tokens; pos++) {
        OfortTokenType type = I->tokens[pos].type;
        if (type == FTOK_LPAREN) {
            depth++;
        } else if (type == FTOK_RPAREN) {
            depth--;
            if (depth == 0) return 0;
        } else if (type == FTOK_COMMA && depth == 1) {
            return 1;
        } else if (type == FTOK_NEWLINE || type == FTOK_EOF) {
            return 0;
        }
    }
    return 0;
}

static OfortNode *parse_implied_do(OfortInterpreter *I) {
    OfortToken *lt = expect(I, FTOK_LPAREN);
    OfortNode *n = alloc_node(I, FND_IMPLIED_DO);
    int cap = 0;
    n->line = lt->line;
    n->stmts = NULL;
    n->n_stmts = 0;

    while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
        OfortNode *item = parse_io_item(I);
        if (n->n_stmts >= cap) {
            cap = cap ? cap * 2 : 4;
            n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
        }
        n->stmts[n->n_stmts++] = item;

        expect(I, FTOK_COMMA);
        if ((check(I, FTOK_IDENT) || check(I, FTOK_IN) || check(I, FTOK_OUT)) &&
            peek_ahead(I, 1)->type == FTOK_ASSIGN) {
            OfortToken *var = advance(I);
            if (var->type == FTOK_IN) copy_cstr(n->name, sizeof(n->name), "in");
            else if (var->type == FTOK_OUT) copy_cstr(n->name, sizeof(n->name), "out");
            else copy_cstr(n->name, sizeof(n->name), var->str_val);
            advance(I); /* = */
            n->children[0] = parse_expr(I);
            expect(I, FTOK_COMMA);
            n->children[1] = parse_expr(I);
            if (check(I, FTOK_COMMA)) {
                advance(I);
                n->children[2] = parse_expr(I);
            } else {
                OfortNode *one = alloc_node(I, FND_INT_LIT);
                one->int_val = 1;
                one->line = n->line;
                n->children[2] = one;
            }
            n->n_children = 3;
            expect(I, FTOK_RPAREN);
            return n;
        }
    }

    ofort_error(I, "Expected implied DO control");
    return n;
}

static OfortNode *parse_io_item(OfortInterpreter *I) {
    if (check(I, FTOK_LPAREN) && paren_item_has_top_level_comma(I)) {
        return parse_implied_do(I);
    }
    if (check(I, FTOK_LPAREN)) {
        OfortToken *t = advance(I);
        OfortNode *inner = parse_expr(I);
        expect(I, FTOK_RPAREN);
        if (check(I, FTOK_POWER)) {
            advance(I);
            OfortNode *n = alloc_node(I, FND_POWER);
            n->children[0] = inner;
            n->children[1] = parse_power(I);
            n->n_children = 2;
            n->line = t->line;
            return n;
        }
        return inner;
    }
    return parse_expr(I);
}

static OfortNode *parse_print(OfortInterpreter *I) {
    OfortToken *pt = advance(I); /* PRINT */
    OfortNode *n = alloc_node(I, FND_PRINT);
    n->line = pt->line;
    n->stmts = NULL;
    n->n_stmts = 0;
    int cap = 0;

    /* format specifier: PRINT *, ... or PRINT '(fmt)', ... or PRINT "(fmt)", ... */
    if (check(I, FTOK_STAR)) {
        advance(I);
        n->format_str[0] = '\0'; /* list-directed */
    } else if (check(I, FTOK_STRING_LIT)) {
        copy_cstr(n->format_str, sizeof(n->format_str), peek(I)->str_val);
        advance(I);
    } else {
        n->format_str[0] = '\0';
    }

    /* consume comma after format */
    if (check(I, FTOK_COMMA)) advance(I);

    /* parse output items */
    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        OfortNode *item = parse_io_item(I);
        if (n->n_stmts >= cap) {
            cap = cap ? cap * 2 : 8;
            n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
        }
        n->stmts[n->n_stmts++] = item;
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }
    return n;
}

static OfortNode *parse_write(OfortInterpreter *I) {
    OfortToken *wt = advance(I); /* WRITE */
    OfortNode *n = alloc_node(I, FND_WRITE);
    n->line = wt->line;
    n->stmts = NULL;
    n->n_stmts = 0;
    int cap = 0;
    n->format_str[0] = '\0';
    n->bool_val = 0; /* unit-only WRITE(unit) stream-style extension */

    /* WRITE(unit, fmt) or WRITE(unit=..., fmt=...) */
    expect(I, FTOK_LPAREN);
    int positional = 0;
    int saw_fmt = 0;
    while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
        if (check_keyword_arg(I)) {
            const char *name = token_arg_name(advance(I));
            advance(I); /* = */
            if (str_eq_nocase(name, "unit")) {
                if (check(I, FTOK_STAR)) {
                    advance(I);
                } else {
                    n->children[0] = parse_expr(I);
                    if (n->n_children < 1) n->n_children = 1;
                }
            } else if (str_eq_nocase(name, "fmt")) {
                saw_fmt = 1;
                if (check(I, FTOK_STAR)) {
                    advance(I);
                } else if (check(I, FTOK_STRING_LIT)) {
                    copy_cstr(n->format_str, sizeof(n->format_str), peek(I)->str_val);
                    advance(I);
                } else if (check(I, FTOK_INT_LIT)) {
                    advance(I); /* format label number, ignore */
                } else {
                    parse_expr(I);
                }
            } else {
                /* Other WRITE controls are currently ignored. */
                if (check(I, FTOK_STAR) || check(I, FTOK_INT_LIT) ||
                    check(I, FTOK_STRING_LIT) || check(I, FTOK_IDENT)) {
                    advance(I);
                } else {
                    parse_expr(I);
                }
            }
        } else if (check(I, FTOK_STAR)) {
            if (positional > 0) saw_fmt = 1;
            advance(I);
        } else if (check(I, FTOK_STRING_LIT)) {
            if (positional > 0) saw_fmt = 1;
            copy_cstr(n->format_str, sizeof(n->format_str), peek(I)->str_val);
            advance(I);
        } else if (check(I, FTOK_INT_LIT)) {
            if (positional > 0) saw_fmt = 1;
            advance(I); /* format label number, ignore */
        } else if (positional == 0) {
            n->children[0] = parse_expr(I);
            n->n_children = 1;
        } else {
            parse_expr(I);
        }
        positional++;
        if (check(I, FTOK_COMMA)) {
            advance(I);
        } else if (check(I, FTOK_RPAREN)) {
            break;
        } else {
            break;
        }
    }
    expect(I, FTOK_RPAREN);
    if (n->children[0] && !saw_fmt && positional == 1) {
        n->bool_val = 1;
    }

    /* output items */
    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        OfortNode *item = parse_io_item(I);
        if (n->n_stmts >= cap) {
            cap = cap ? cap * 2 : 8;
            n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
        }
        n->stmts[n->n_stmts++] = item;
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }
    return n;
}

static OfortNode *parse_read_stmt(OfortInterpreter *I) {
    advance(I); /* READ */
    OfortNode *n = alloc_node(I, FND_READ_STMT);
    n->stmts = NULL; n->n_stmts = 0;
    int cap = 0;
    n->format_str[0] = '\0';
    n->bool_val = 0; /* unit-only READ(unit) stream-style extension */

    /* READ(unit, fmt) or READ(unit=..., fmt=..., iostat=...) */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        int positional = 0;
        int saw_fmt = 0;
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            if (check_keyword_arg(I)) {
                const char *name = token_arg_name(advance(I));
                advance(I); /* = */
                if (str_eq_nocase(name, "unit")) {
                    if (check(I, FTOK_STAR)) {
                        advance(I);
                    } else {
                        n->children[0] = parse_expr(I);
                        n->n_children = 1;
                    }
                } else if (str_eq_nocase(name, "fmt")) {
                    saw_fmt = 1;
                    if (check(I, FTOK_STAR)) advance(I);
                    else if (check(I, FTOK_STRING_LIT)) {
                        copy_cstr(n->format_str, sizeof(n->format_str), peek(I)->str_val);
                        advance(I);
                    } else {
                        parse_expr(I);
                    }
                } else {
                    parse_expr(I);
                }
            } else if (check(I, FTOK_STAR)) {
                if (positional > 0) saw_fmt = 1;
                advance(I);
            } else if (check(I, FTOK_STRING_LIT)) {
                if (positional > 0) saw_fmt = 1;
                copy_cstr(n->format_str, sizeof(n->format_str), peek(I)->str_val);
                advance(I);
            } else if (positional == 0) {
                n->children[0] = parse_expr(I);
                n->n_children = 1;
            } else {
                parse_expr(I);
            }
            positional++;
            if (check(I, FTOK_COMMA)) advance(I);
            else break;
        }
        expect(I, FTOK_RPAREN);
        if (n->children[0] && !saw_fmt && positional == 1) {
            n->bool_val = 1;
        }
    } else if (check(I, FTOK_STAR)) {
        advance(I);
        if (check(I, FTOK_COMMA)) advance(I);
    }

    /* variable list */
    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        OfortNode *item = parse_expr(I);
        if (n->n_stmts >= cap) {
            cap = cap ? cap * 2 : 8;
            n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
        }
        n->stmts[n->n_stmts++] = item;
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }
    return n;
}

static OfortNode *parse_open_stmt(OfortInterpreter *I) {
    OfortToken *ot = advance(I); /* OPEN */
    OfortNode *n = alloc_node(I, FND_OPEN);
    n->line = ot->line;

    expect(I, FTOK_LPAREN);
    while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
        if (check(I, FTOK_IDENT) && peek_ahead(I, 1)->type == FTOK_ASSIGN) {
            OfortToken *name = advance(I);
            advance(I); /* = */
            if (str_eq_nocase(name->str_val, "unit")) {
                n->children[0] = parse_expr(I);
                if (n->n_children < 1) n->n_children = 1;
            } else if (str_eq_nocase(name->str_val, "file")) {
                n->children[1] = parse_expr(I);
                if (n->n_children < 2) n->n_children = 2;
            } else {
                parse_expr(I);
            }
        } else {
            if (!n->children[0]) {
                n->children[0] = parse_expr(I);
                if (n->n_children < 1) n->n_children = 1;
            } else {
                parse_expr(I);
            }
        }
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }
    expect(I, FTOK_RPAREN);
    return n;
}

static OfortNode *parse_close_stmt(OfortInterpreter *I) {
    OfortToken *ct = advance(I); /* CLOSE */
    OfortNode *n = alloc_node(I, FND_CLOSE);
    n->line = ct->line;

    expect(I, FTOK_LPAREN);
    while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
        if (check(I, FTOK_IDENT) && peek_ahead(I, 1)->type == FTOK_ASSIGN) {
            OfortToken *name = advance(I);
            advance(I); /* = */
            if (str_eq_nocase(name->str_val, "unit")) {
                n->children[0] = parse_expr(I);
                n->n_children = 1;
            } else {
                parse_expr(I);
            }
        } else if (!n->children[0]) {
            n->children[0] = parse_expr(I);
            n->n_children = 1;
        } else {
            parse_expr(I);
        }
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }
    expect(I, FTOK_RPAREN);
    return n;
}

static OfortNode *parse_subroutine(OfortInterpreter *I) {
    OfortToken *st = advance(I); /* SUBROUTINE */
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_SUBROUTINE);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    n->line = st->line;
    n->n_params = 0;

    /* parameter list */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *param = expect(I, FTOK_IDENT);
            copy_cstr(n->param_names[n->n_params], sizeof(n->param_names[n->n_params]), param->str_val);
            n->param_types[n->n_params] = FVAL_VOID; /* resolved later */
            n->param_intents[n->n_params] = 0;
            n->param_optional[n->n_params] = 0;
            n->n_params++;
            if (check(I, FTOK_COMMA)) advance(I);
        }
        expect(I, FTOK_RPAREN);
    }
    skip_newlines(I);

    /* body */
    n->children[0] = parse_block_until_end(I, "SUBROUTINE");
    n->n_children = 1;
    consume_end(I, "SUBROUTINE");
    return n;
}

static OfortNode *parse_function_with_type(OfortInterpreter *I, OfortValType result_type) {
    OfortToken *ft = advance(I); /* FUNCTION */
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_FUNCTION);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    n->line = ft->line;
    n->val_type = result_type;
    n->n_params = 0;
    n->result_name[0] = '\0';

    /* parameter list */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *param = expect(I, FTOK_IDENT);
            copy_cstr(n->param_names[n->n_params], sizeof(n->param_names[n->n_params]), param->str_val);
            n->param_types[n->n_params] = FVAL_VOID;
            n->param_intents[n->n_params] = 0;
            n->param_optional[n->n_params] = 0;
            n->n_params++;
            if (check(I, FTOK_COMMA)) advance(I);
        }
        expect(I, FTOK_RPAREN);
    }

    /* optional RESULT(name) */
    if (check(I, FTOK_RESULT)) {
        advance(I);
        expect(I, FTOK_LPAREN);
        OfortToken *res = expect(I, FTOK_IDENT);
        copy_cstr(n->result_name, sizeof(n->result_name), res->str_val);
        expect(I, FTOK_RPAREN);
    }
    skip_newlines(I);

    /* body */
    n->children[0] = parse_block_until_end(I, "FUNCTION");
    n->n_children = 1;
    consume_end(I, "FUNCTION");
    return n;
}

static OfortNode *parse_function(OfortInterpreter *I) {
    return parse_function_with_type(I, FVAL_INTEGER);
}

static OfortNode *parse_typed_function(OfortInterpreter *I) {
    OfortToken *type_tok = advance(I);
    OfortValType result_type = token_to_valtype(type_tok->type);

    if (check(I, FTOK_LPAREN)) {
        int depth = 0;
        do {
            if (check(I, FTOK_LPAREN)) depth++;
            else if (check(I, FTOK_RPAREN)) depth--;
            advance(I);
        } while (depth > 0 && !check(I, FTOK_EOF));
    }

    return parse_function_with_type(I, result_type);
}

static OfortNode *parse_module(OfortInterpreter *I) {
    OfortToken *mt = advance(I); /* MODULE */
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_MODULE);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    n->line = mt->line;
    skip_newlines(I);

    /* body (may include CONTAINS section) */
    n->children[0] = parse_block_until_end(I, "MODULE");
    n->n_children = 1;
    consume_end(I, "MODULE");
    return n;
}

static OfortNode *parse_type_def(OfortInterpreter *I) {
    OfortToken *tt = advance(I); /* TYPE */
    /* TYPE :: name */
    if (check(I, FTOK_DCOLON)) advance(I);
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_TYPE_DEF);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    n->line = tt->line;
    skip_newlines(I);

    /* parse fields until END TYPE */
    n->stmts = NULL; n->n_stmts = 0;
    int cap = 0;
    while (!check_end(I, "TYPE") && !check(I, FTOK_EOF)) {
        skip_newlines(I);
        if (check_end(I, "TYPE")) break;
        OfortNode *s = parse_statement(I);
        if (s) {
            if (n->n_stmts >= cap) {
                cap = cap ? cap * 2 : 8;
                n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
            }
            n->stmts[n->n_stmts++] = s;
        }
        skip_newlines(I);
    }
    consume_end(I, "TYPE");
    return n;
}

static OfortNode *parse_allocate(OfortInterpreter *I) {
    OfortToken *at = advance(I); /* ALLOCATE */
    OfortNode *n = alloc_node(I, FND_ALLOCATE);
    OfortNode *source_expr = NULL;
    OfortNode *mold_expr = NULL;
    n->line = at->line;
    expect(I, FTOK_LPAREN);
    /* parse: array_name(dim1, dim2, ...) */
    OfortToken *name = expect(I, FTOK_IDENT);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    n->stmts = NULL; n->n_stmts = 0;
    int cap = 0;
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortNode *dim = parse_expr(I);
            if (n->n_stmts >= cap) {
                cap = cap ? cap * 2 : 4;
                n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
            }
            n->stmts[n->n_stmts++] = dim;
            if (check(I, FTOK_COMMA)) advance(I);
        }
        expect(I, FTOK_RPAREN);
    }
    while (check(I, FTOK_COMMA)) {
        advance(I);
        if (check_keyword_arg(I)) {
            const char *arg_name = token_arg_name(advance(I));
            advance(I); /* = */
            if (str_eq_nocase(arg_name, "source")) {
                source_expr = parse_expr(I);
            } else if (str_eq_nocase(arg_name, "mold")) {
                mold_expr = parse_expr(I);
            } else {
                parse_expr(I);
            }
        } else {
            parse_expr(I);
        }
    }
    n->children[0] = source_expr;
    n->children[1] = mold_expr;
    n->n_children = (source_expr || mold_expr) ? 2 : 0;
    expect(I, FTOK_RPAREN);
    return n;
}

static OfortNode *parse_deallocate(OfortInterpreter *I) {
    OfortToken *dt = advance(I); /* DEALLOCATE */
    OfortNode *n = alloc_node(I, FND_DEALLOCATE);
    n->line = dt->line;
    expect(I, FTOK_LPAREN);
    OfortToken *name = expect(I, FTOK_IDENT);
    copy_cstr(n->name, sizeof(n->name), name->str_val);
    expect(I, FTOK_RPAREN);
    return n;
}

static char implicit_type_code(OfortValType type) {
    switch (type) {
        case FVAL_INTEGER: return 'I';
        case FVAL_REAL: return 'R';
        case FVAL_DOUBLE: return 'D';
        case FVAL_LOGICAL: return 'L';
        case FVAL_CHARACTER: return 'C';
        default: return 0;
    }
}

static int token_letter_index(OfortToken *t) {
    char c = '\0';
    if (t->type == FTOK_IDENT && t->str_val[0]) {
        c = t->str_val[0];
    } else if (t->start && t->length > 0) {
        c = t->start[0];
    }
    c = (char)toupper((unsigned char)c);
    if (c < 'A' || c > 'Z') return -1;
    return c - 'A';
}

static void skip_balanced_parens(OfortInterpreter *I) {
    if (!check(I, FTOK_LPAREN)) return;
    advance(I);
    int depth = 1;
    while (depth > 0 && !check(I, FTOK_EOF)) {
        if (check(I, FTOK_LPAREN)) depth++;
        else if (check(I, FTOK_RPAREN)) depth--;
        advance(I);
    }
}

static OfortNode *parse_implicit_stmt(OfortInterpreter *I) {
    OfortToken *t = advance(I); /* IMPLICIT */
    OfortNode *n = alloc_node(I, FND_IMPLICIT_NONE);
    n->line = t->line;

    if (check(I, FTOK_NONE)) {
        advance(I);
        n->bool_val = 1;
        return n;
    }

    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        OfortValType vtype;
        if (!is_type_keyword(peek(I)->type))
            ofort_error(I, "Expected type in IMPLICIT statement");
        vtype = token_to_valtype(advance(I)->type);

        if (check(I, FTOK_LPAREN) && vtype == FVAL_CHARACTER) {
            skip_balanced_parens(I);
        } else if (check(I, FTOK_LPAREN) &&
                   (vtype == FVAL_INTEGER || vtype == FVAL_REAL || vtype == FVAL_DOUBLE)) {
            OfortToken *after_lparen = peek_ahead(I, 1);
            if (!(after_lparen->type == FTOK_IDENT || after_lparen->type == FTOK_IN || after_lparen->type == FTOK_OUT)) {
                skip_balanced_parens(I);
            }
        }

        expect(I, FTOK_LPAREN);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *lo_tok = advance(I);
            int lo = token_letter_index(lo_tok);
            int hi = lo;
            if (lo < 0) ofort_error(I, "Expected letter in IMPLICIT range");
            if (check(I, FTOK_MINUS)) {
                advance(I);
                OfortToken *hi_tok = advance(I);
                hi = token_letter_index(hi_tok);
                if (hi < 0) ofort_error(I, "Expected letter in IMPLICIT range");
            }
            if (lo > hi) {
                int tmp = lo;
                lo = hi;
                hi = tmp;
            }
            for (int i = lo; i <= hi; i++) n->implicit_types[i] = implicit_type_code(vtype);
            if (check(I, FTOK_COMMA)) advance(I);
            else break;
        }
        expect(I, FTOK_RPAREN);
        if (check(I, FTOK_COMMA)) advance(I);
        else break;
    }

    return n;
}

static OfortNode *parse_access_stmt(OfortInterpreter *I) {
    OfortToken *t = advance(I);
    OfortNode *n = alloc_node(I, FND_ACCESS);
    n->line = t->line;
    n->bool_val = token_ident_upper(t, "PUBLIC") ? 1 : 0;
    n->n_params = 0;

    if (check(I, FTOK_DCOLON)) advance(I);
    while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
        if (check(I, FTOK_COMMA)) {
            advance(I);
            continue;
        }
        if (check(I, FTOK_IDENT) && n->n_params < OFORT_MAX_PARAMS) {
            OfortToken *name = advance(I);
            copy_cstr(n->param_names[n->n_params++], sizeof(n->param_names[0]), name->str_val);
        } else {
            advance(I);
        }
    }
    return n;
}

static OfortNode *parse_statement(OfortInterpreter *I) {
    skip_newlines(I);
    OfortToken *t = peek(I);
    if (t->type == FTOK_EOF) return NULL;

    /* Statement label/name prefix, e.g. "outer: do ..." */
    if (t->type == FTOK_IDENT && peek_ahead(I, 1)->type == FTOK_COLON) {
        advance(I);
        advance(I);
        skip_newlines(I);
        t = peek(I);
        if (t->type == FTOK_EOF) return NULL;
    }

    /* IMPLICIT NONE */
    if (t->type == FTOK_IMPLICIT) {
        return parse_implicit_stmt(I);
    }

    /* Module access statements: PUBLIC, PRIVATE, PUBLIC :: x, PRIVATE :: x */
    if (token_ident_upper(t, "PUBLIC") || token_ident_upper(t, "PRIVATE")) {
        return parse_access_stmt(I);
    }

    /* USE module_name */
    if (t->type == FTOK_USE) {
        advance(I);
        while (check(I, FTOK_COMMA)) {
            advance(I);
            while (!check(I, FTOK_DCOLON) && !check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
                advance(I);
                if (check(I, FTOK_COMMA)) {
                    advance(I);
                } else if (check(I, FTOK_DCOLON)) {
                    break;
                } else {
                    break;
                }
            }
            if (check(I, FTOK_DCOLON)) break;
        }
        if (check(I, FTOK_DCOLON)) advance(I);
        OfortToken *mn = expect(I, FTOK_IDENT);
        OfortNode *n = alloc_node(I, FND_USE);
        copy_cstr(n->name, sizeof(n->name), mn->str_val);
        n->line = t->line;
        while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) {
            advance(I);
        }
        return n;
    }

    /* CONTAINS */
    if (t->type == FTOK_CONTAINS) {
        advance(I);
        /* just skip it; subroutines/functions follow */
        return NULL;
    }

    /* Generic INTERFACE blocks are skipped for now. */
    if (token_ident_upper(t, "INTERFACE")) {
        skip_interface_block(I);
        return NULL;
    }

    /* Standalone PARAMETER statement: PARAMETER (name = expr, ...) */
    if (t->type == FTOK_PARAMETER) {
        OfortToken *pt = advance(I);
        OfortNode *block = alloc_node(I, FND_BLOCK);
        int cap = 0;
        block->line = pt->line;
        block->stmts = NULL;
        block->n_stmts = 0;
        expect(I, FTOK_LPAREN);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *name = expect(I, FTOK_IDENT);
            OfortNode *param = alloc_node(I, FND_PARAMDECL);
            copy_cstr(param->name, sizeof(param->name), name->str_val);
            param->line = name->line;
            expect(I, FTOK_ASSIGN);
            param->children[0] = parse_expr(I);
            param->n_children = 1;
            if (block->n_stmts >= cap) {
                cap = cap ? cap * 2 : 4;
                block->stmts = (OfortNode **)realloc(block->stmts, sizeof(OfortNode *) * cap);
            }
            block->stmts[block->n_stmts++] = param;
            if (check(I, FTOK_COMMA)) advance(I);
            else break;
        }
        expect(I, FTOK_RPAREN);
        return block;
    }

    /* declarations */
    if (is_type_keyword(t->type)) {
        if (peek_ahead(I, 1)->type == FTOK_FUNCTION ||
            (peek_ahead(I, 1)->type == FTOK_LPAREN && peek_ahead(I, 3)->type == FTOK_FUNCTION)) {
            return parse_typed_function(I);
        }
        /* Could be a declaration or a function with type prefix */
        /* Look ahead for :: or ident followed by = or ( or , */
        /* Check if this is "TYPE :: name" (type definition) when token is FTOK_TYPE */
        /* Since TYPE is mapped to FTOK_TYPE for derived types too, handle in TYPE case below */
        return parse_declaration(I);
    }

    /* TYPE definition (derived type) */
    if (t->type == FTOK_TYPE) {
        /* Distinguish between TYPE :: typename (definition) and TYPE(typename) :: var (declaration) */
        OfortToken *next = peek_ahead(I, 1);
        if (next->type == FTOK_DCOLON || next->type == FTOK_IDENT) {
            return parse_type_def(I);
        }
        /* TYPE(typename) is used as a type — skip for now */
        advance(I);
        return NULL;
    }

    /* PROGRAM */
    if (t->type == FTOK_PROGRAM) {
        advance(I);
        OfortToken *name = NULL;
        if (check(I, FTOK_IDENT)) name = advance(I);
        skip_newlines(I);
        OfortNode *n = alloc_node(I, FND_PROGRAM);
        if (name) copy_cstr(n->name, sizeof(n->name), name->str_val);
        n->line = t->line;
        n->children[0] = parse_block_until_end(I, "PROGRAM");
        n->n_children = 1;
        consume_end(I, "PROGRAM");
        return n;
    }

    /* SUBROUTINE */
    if (t->type == FTOK_SUBROUTINE) return parse_subroutine(I);

    /* FUNCTION */
    if (t->type == FTOK_FUNCTION) return parse_function(I);

    /* MODULE */
    if (t->type == FTOK_MODULE) return parse_module(I);

    /* IF */
    if (t->type == FTOK_IF) return parse_if(I);

    /* DO */
    if (t->type == FTOK_DO) return parse_do(I);

    /* SELECT CASE */
    if (t->type == FTOK_SELECT) return parse_select_case(I);

    /* PRINT */
    if (t->type == FTOK_PRINT) return parse_print(I);

    /* WRITE */
    if (t->type == FTOK_WRITE) return parse_write(I);

    /* READ */
    if (t->type == FTOK_READ) return parse_read_stmt(I);

    /* OPEN/CLOSE */
    if (t->type == FTOK_OPEN) return parse_open_stmt(I);
    if (t->type == FTOK_CLOSE) return parse_close_stmt(I);

    /* CALL */
    if (t->type == FTOK_CALL) {
        OfortToken *ct = advance(I);
        OfortToken *name = expect(I, FTOK_IDENT);
        OfortNode *n = alloc_node(I, FND_CALL);
        copy_cstr(n->name, sizeof(n->name), name->str_val);
        n->line = ct->line;
        n->stmts = NULL; n->n_stmts = 0;
        int cap = 0;
        if (check(I, FTOK_LPAREN)) {
            advance(I);
            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                const char *arg_name = NULL;
                if (check_keyword_arg(I)) {
                    arg_name = token_arg_name(advance(I));
                    advance(I); /* = */
                }
                OfortNode *arg = parse_expr(I);
                if (n->n_stmts >= cap) {
                    cap = cap ? cap * 2 : 8;
                    n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
                }
                if (arg_name) copy_cstr(n->param_names[n->n_stmts], sizeof(n->param_names[n->n_stmts]), arg_name);
                n->stmts[n->n_stmts++] = arg;
                if (check(I, FTOK_COMMA)) advance(I);
            }
            expect(I, FTOK_RPAREN);
        }
        return n;
    }

    /* RETURN */
    if (t->type == FTOK_RETURN) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_RETURN);
        n->line = t->line;
        return n;
    }

    /* EXIT */
    if (t->type == FTOK_EXIT) {
        advance(I);
        if (check(I, FTOK_IDENT)) advance(I); /* optional construct name */
        OfortNode *n = alloc_node(I, FND_EXIT);
        n->line = t->line;
        return n;
    }

    /* CYCLE */
    if (t->type == FTOK_CYCLE) {
        advance(I);
        if (check(I, FTOK_IDENT)) advance(I); /* optional construct name */
        OfortNode *n = alloc_node(I, FND_CYCLE);
        n->line = t->line;
        return n;
    }

    /* STOP */
    if (t->type == FTOK_STOP) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_STOP);
        n->line = t->line;
        /* optional stop message */
        if (check(I, FTOK_STRING_LIT)) {
            copy_cstr(n->str_val, sizeof(n->str_val), peek(I)->str_val);
            advance(I);
        } else if (check(I, FTOK_INT_LIT)) {
            snprintf(n->str_val, OFORT_MAX_STRLEN, "%lld", peek(I)->int_val);
            advance(I);
        }
        return n;
    }

    /* ALLOCATE */
    if (t->type == FTOK_ALLOCATE) return parse_allocate(I);

    /* DEALLOCATE */
    if (t->type == FTOK_DEALLOCATE) return parse_deallocate(I);

    /* END (bare) — shouldn't be reached normally */
    if (t->type == FTOK_END) {
        skip_to_next_line(I);
        return NULL;
    }

    /* DATA statement: DATA var /value/ — simplified */
    if (t->type == FTOK_DATA) {
        advance(I);
        /* skip until newline */
        while (!check(I, FTOK_NEWLINE) && !check(I, FTOK_EOF)) advance(I);
        return NULL;
    }

    /* Expression statement or assignment: ident = expr, ident(args) = expr, or bare expr */
    if (t->type == FTOK_IDENT || t->type == FTOK_INT_LIT || t->type == FTOK_REAL_LIT ||
        t->type == FTOK_STRING_LIT || t->type == FTOK_TRUE || t->type == FTOK_FALSE ||
        t->type == FTOK_LPAREN || t->type == FTOK_MINUS || t->type == FTOK_PLUS ||
        t->type == FTOK_NOT) {
        OfortNode *expr = parse_expr(I);
        if (check(I, FTOK_POINTER_ASSIGN)) {
            if (expr->type != FND_IDENT && expr->type != FND_FUNC_CALL) {
                ofort_error(I, "Invalid pointer assignment target at line %d", t->line);
            }
            advance(I);
            OfortNode *rhs = parse_expr(I);
            OfortNode *n = alloc_node(I, FND_POINTER_ASSIGN);
            n->children[0] = expr;
            n->children[1] = rhs;
            n->n_children = 2;
            n->line = t->line;
            return n;
        }
        if (check(I, FTOK_ASSIGN)) {
            if (expr->type != FND_IDENT && expr->type != FND_FUNC_CALL && expr->type != FND_MEMBER) {
                ofort_error(I, "Invalid assignment target at line %d", t->line);
            }
            advance(I);
            OfortNode *rhs = parse_expr(I);
            OfortNode *n = alloc_node(I, FND_ASSIGN);
            n->children[0] = expr;
            n->children[1] = rhs;
            n->n_children = 2;
            n->line = t->line;
            return n;
        }
        /* Expression statement (e.g., function call as statement) */
        OfortNode *n = alloc_node(I, FND_EXPR_STMT);
        n->children[0] = expr;
        n->n_children = 1;
        n->line = t->line;
        return n;
    }

    /* skip unknown */
    advance(I);
    return NULL;
}

static OfortNode *parse_block_until_end(OfortInterpreter *I, const char *end_keyword) {
    OfortNode *block = alloc_node(I, FND_BLOCK);
    block->stmts = NULL;
    block->n_stmts = 0;
    int cap = 0;

    while (!check_end(I, end_keyword) && peek(I)->type != FTOK_EOF) {
        /* Also break on CONTAINS for modules */
        if (end_keyword && strcmp(end_keyword, "MODULE") == 0 && check(I, FTOK_CONTAINS)) {
            advance(I);
            skip_newlines(I);
            /* parse contained procedures */
            while (!check_end(I, end_keyword) && peek(I)->type != FTOK_EOF) {
                skip_newlines(I);
                if (check_end(I, end_keyword)) break;
                OfortNode *s = parse_statement(I);
                if (s) {
                    if (block->n_stmts >= cap) {
                        cap = cap ? cap * 2 : 8;
                        block->stmts = (OfortNode **)realloc(block->stmts, sizeof(OfortNode *) * cap);
                    }
                    block->stmts[block->n_stmts++] = s;
                }
                skip_newlines(I);
            }
            break;
        }
        skip_newlines(I);
        if (check_end(I, end_keyword)) break;
        OfortNode *s = parse_statement(I);
        if (s) {
            if (block->n_stmts >= cap) {
                cap = cap ? cap * 2 : 8;
                block->stmts = (OfortNode **)realloc(block->stmts, sizeof(OfortNode *) * cap);
            }
            block->stmts[block->n_stmts++] = s;
        }
        skip_newlines(I);
    }
    return block;
}

static OfortNode *parse_program(OfortInterpreter *I) {
    OfortNode *prog = alloc_node(I, FND_BLOCK);
    prog->stmts = NULL;
    prog->n_stmts = 0;
    int cap = 0;

    skip_newlines(I);
    while (peek(I)->type != FTOK_EOF) {
        OfortNode *s = parse_statement(I);
        if (s) {
            if (prog->n_stmts >= cap) {
                cap = cap ? cap * 2 : 16;
                prog->stmts = (OfortNode **)realloc(prog->stmts, sizeof(OfortNode *) * cap);
            }
            prog->stmts[prog->n_stmts++] = s;
        }
        skip_newlines(I);
    }
    return prog;
}

/* ══════════════════════════════════════════════
 *  EVALUATOR
 * ══════════════════════════════════════════════ */

static OfortValue default_value(OfortValType vtype, int char_len) {
    switch (vtype) {
        case FVAL_INTEGER: return make_integer(0);
        case FVAL_REAL: return make_real(0.0);
        case FVAL_DOUBLE: return make_double(0.0);
        case FVAL_COMPLEX: return make_complex(0.0, 0.0);
        case FVAL_CHARACTER: {
            char *s = (char *)calloc(char_len + 1, 1);
            memset(s, ' ', char_len);
            OfortValue v = make_character(s);
            free(s);
            return v;
        }
        case FVAL_LOGICAL: return make_logical(0);
        default: return make_void_val();
    }
}

static int eval_character_length(OfortInterpreter *I, OfortNode *n) {
    int char_len = n->char_len;
    if (n->char_len_expr) {
        OfortValue v = eval_node(I, n->char_len_expr);
        char_len = (int)val_to_int(v);
        free_value(&v);
    }
    if (char_len < 0) char_len = 0;
    if (char_len >= OFORT_MAX_STRLEN) char_len = OFORT_MAX_STRLEN - 1;
    return char_len;
}

static OfortValue make_array_with_char_len(OfortValType elem_type, int *dims, int n_dims, int char_len) {
    OfortValue v; memset(&v, 0, sizeof(v));
    v.type = FVAL_ARRAY;
    int total = 1;
    int i;
    for (i = 0; i < n_dims; i++) {
        v.v.arr.dims[i] = dims[i];
        total *= dims[i];
    }
    v.v.arr.n_dims = n_dims;
    v.v.arr.len = total;
    v.v.arr.cap = total;
    v.v.arr.elem_type = elem_type;
    v.v.arr.allocated = 1;
    v.v.arr.data = (OfortValue *)calloc(total, sizeof(OfortValue));
    for (i = 0; i < total; i++)
        v.v.arr.data[i] = default_value(elem_type, char_len);
    return v;
}

static OfortValue make_array(OfortValType elem_type, int *dims, int n_dims) {
    return make_array_with_char_len(elem_type, dims, n_dims, 1);
}

static OfortValue make_array_from_decl(OfortInterpreter *I, OfortNode *n) {
    int dims[7];
    int ndims = n->n_dims;

    for (int i = 0; i < ndims; i++) {
        dims[i] = n->dims[i];
        if (dims[i] <= 0 && n->stmts && i < n->n_stmts && n->stmts[i]) {
            OfortValue dv = eval_node(I, n->stmts[i]);
            dims[i] = (int)val_to_int(dv);
            free_value(&dv);
        }
        if (dims[i] < 0) dims[i] = 0;
    }

    return make_array_with_char_len(n->val_type, dims, ndims, eval_character_length(I, n));
}

typedef struct {
    int start;
    int end;
    int step;
    int is_slice;
    int count;
} OfortSubscriptRange;

static int eval_subscript_range(OfortInterpreter *I, OfortNode *sub, int dim_extent,
                                OfortSubscriptRange *range) {
    range->start = 1;
    range->end = dim_extent;
    range->step = 1;
    range->is_slice = 0;
    range->count = 1;

    if (sub->type == FND_SLICE) {
        range->is_slice = 1;
        if (sub->children[0]) {
            OfortValue v = eval_node(I, sub->children[0]);
            range->start = (int)val_to_int(v);
            free_value(&v);
        }
        if (sub->children[1]) {
            OfortValue v = eval_node(I, sub->children[1]);
            range->end = (int)val_to_int(v);
            free_value(&v);
        }
        if (sub->n_children >= 3 && sub->children[2]) {
            OfortValue v = eval_node(I, sub->children[2]);
            range->step = (int)val_to_int(v);
            free_value(&v);
            if (range->step == 0) ofort_error(I, "Array section stride cannot be zero");
        }
        range->count = 0;
        for (int i = range->start; range->step > 0 ? i <= range->end : i >= range->end; i += range->step) {
            range->count++;
        }
        return 1;
    }

    OfortValue v = eval_node(I, sub);
    range->start = (int)val_to_int(v);
    range->end = range->start;
    free_value(&v);
    return 0;
}

static int section_linear_index(OfortValue *arr, int *subscripts, int nsubs) {
    int index = 0;
    int stride = 1;
    for (int i = 0; i < nsubs; i++) {
        index += (subscripts[i] - 1) * stride;
        if (i < arr->v.arr.n_dims) {
            stride *= arr->v.arr.dims[i];
        }
    }
    return index;
}

static void copy_section_recursive(OfortInterpreter *I, OfortValue *src, OfortValue *dst,
                                   OfortSubscriptRange *ranges, int nranges,
                                   int dim, int *subscripts, int *out_index) {
    if (dim == nranges) {
        int src_index = section_linear_index(src, subscripts, nranges);
        if (src_index < 0 || src_index >= src->v.arr.len)
            ofort_error(I, "Array section index out of bounds");
        free_value(&dst->v.arr.data[*out_index]);
        dst->v.arr.data[*out_index] = copy_value(src->v.arr.data[src_index]);
        (*out_index)++;
        return;
    }

    for (int idx = ranges[dim].start;
         ranges[dim].step > 0 ? idx <= ranges[dim].end : idx >= ranges[dim].end;
         idx += ranges[dim].step) {
        subscripts[dim] = idx;
        copy_section_recursive(I, src, dst, ranges, nranges, dim + 1, subscripts, out_index);
        if (!ranges[dim].is_slice) break;
    }
}

static OfortValue eval_array_section(OfortInterpreter *I, OfortVar *var, OfortNode *n) {
    int nargs = n->n_stmts;
    OfortSubscriptRange ranges[7];
    int result_dims[7];
    int n_result_dims = 0;
    int has_slice = 0;

    for (int i = 0; i < nargs; i++) {
        int extent = i < var->val.v.arr.n_dims ? var->val.v.arr.dims[i] : var->val.v.arr.len;
        if (eval_subscript_range(I, n->stmts[i], extent, &ranges[i])) {
            has_slice = 1;
            result_dims[n_result_dims++] = ranges[i].count;
        }
    }

    if (!has_slice) {
        int subscripts[7];
        for (int i = 0; i < nargs; i++) subscripts[i] = ranges[i].start;
        int index = section_linear_index(&var->val, subscripts, nargs);
        if (index < 0 || index >= var->val.v.arr.len)
            ofort_error(I, "Array index out of bounds: %d (size %d)", index + 1, var->val.v.arr.len);
        return copy_value(var->val.v.arr.data[index]);
    }

    if (n_result_dims == 0) n_result_dims = 1;
    OfortValue result = make_array(var->val.v.arr.elem_type, result_dims, n_result_dims);
    int subscripts[7] = {0};
    int out_index = 0;
    copy_section_recursive(I, &var->val, &result, ranges, nargs, 0, subscripts, &out_index);
    return result;
}

static int pointer_target_descriptor(OfortInterpreter *I, OfortNode *node,
                                     char *name, size_t name_size,
                                     int *has_slice, int *slice_start, int *slice_end) {
    *has_slice = 0;
    *slice_start = 0;
    *slice_end = 0;
    if (node->type == FND_IDENT) {
        copy_cstr(name, name_size, node->name);
        return 1;
    }
    if (node->type == FND_FUNC_CALL && node->n_stmts == 1 && node->stmts[0]->type == FND_SLICE) {
        OfortVar *var = find_var(I, node->name);
        OfortSubscriptRange range;
        if (!var || var->val.type != FVAL_ARRAY) return 0;
        eval_subscript_range(I, node->stmts[0], var->val.v.arr.len, &range);
        if (!range.is_slice) return 0;
        copy_cstr(name, name_size, node->name);
        *has_slice = 1;
        *slice_start = range.start;
        *slice_end = range.end;
        return 1;
    }
    return 0;
}

static int pointer_matches_target(OfortInterpreter *I, OfortVar *ptr, OfortNode *target) {
    char target_name[256];
    int has_slice, start, end;
    if (!ptr || !ptr->is_pointer || !ptr->pointer_associated) return 0;
    if (target->type == FND_IDENT) {
        OfortVar *target_var = find_var(I, target->name);
        if (target_var && target_var->is_pointer) {
            return target_var->pointer_associated &&
                   str_eq_nocase(ptr->pointer_target, target_var->pointer_target) &&
                   ptr->pointer_has_slice == target_var->pointer_has_slice &&
                   ptr->pointer_slice_start == target_var->pointer_slice_start &&
                   ptr->pointer_slice_end == target_var->pointer_slice_end;
        }
    }
    if (!pointer_target_descriptor(I, target, target_name, sizeof(target_name), &has_slice, &start, &end))
        return 0;
    return str_eq_nocase(ptr->pointer_target, target_name) &&
           ptr->pointer_has_slice == has_slice &&
           (!has_slice || (ptr->pointer_slice_start == start && ptr->pointer_slice_end == end));
}

static int section_element_count(OfortSubscriptRange *ranges, int nranges) {
    int count = 1;
    for (int i = 0; i < nranges; i++) {
        if (ranges[i].is_slice) count *= ranges[i].count;
    }
    return count;
}

static void assign_section_recursive(OfortInterpreter *I, OfortValue *dst, OfortValue *rhs,
                                     OfortSubscriptRange *ranges, int nranges,
                                     int dim, int *subscripts, int *rhs_index) {
    if (dim == nranges) {
        int dst_index = section_linear_index(dst, subscripts, nranges);
        if (dst_index < 0 || dst_index >= dst->v.arr.len)
            ofort_error(I, "Array section index out of bounds");

        OfortValue value;
        if (rhs->type == FVAL_ARRAY) {
            if (*rhs_index >= rhs->v.arr.len)
                ofort_error(I, "Array assignment shape mismatch");
            value = copy_value(rhs->v.arr.data[*rhs_index]);
            (*rhs_index)++;
        } else {
            value = copy_value(*rhs);
        }

        free_value(&dst->v.arr.data[dst_index]);
        dst->v.arr.data[dst_index] = value;
        return;
    }

    for (int idx = ranges[dim].start;
         ranges[dim].step > 0 ? idx <= ranges[dim].end : idx >= ranges[dim].end;
         idx += ranges[dim].step) {
        subscripts[dim] = idx;
        assign_section_recursive(I, dst, rhs, ranges, nranges, dim + 1, subscripts, rhs_index);
        if (!ranges[dim].is_slice) break;
    }
}

static void assign_array_ref(OfortInterpreter *I, OfortVar *var, OfortNode *lhs, OfortValue *rhs) {
    int nargs = lhs->n_stmts;
    OfortSubscriptRange ranges[7];
    int has_slice = 0;

    for (int i = 0; i < nargs; i++) {
        int extent = i < var->val.v.arr.n_dims ? var->val.v.arr.dims[i] : var->val.v.arr.len;
        if (eval_subscript_range(I, lhs->stmts[i], extent, &ranges[i])) {
            has_slice = 1;
        }
    }

    if (!has_slice) {
        int subscripts[7];
        for (int i = 0; i < nargs; i++) subscripts[i] = ranges[i].start;
        int index = section_linear_index(&var->val, subscripts, nargs);
        if (index < 0 || index >= var->val.v.arr.len)
            ofort_error(I, "Array index out of bounds");
        free_value(&var->val.v.arr.data[index]);
        var->val.v.arr.data[index] = copy_value(*rhs);
        return;
    }

    int selected = section_element_count(ranges, nargs);
    if (rhs->type == FVAL_ARRAY && rhs->v.arr.len != selected)
        ofort_error(I, "Array assignment shape mismatch");

    int subscripts[7] = {0};
    int rhs_index = 0;
    assign_section_recursive(I, &var->val, rhs, ranges, nargs, 0, subscripts, &rhs_index);
}

static double random_unit(void) {
    static int seeded = 0;
    if (!seeded) {
        srand((unsigned int)time(NULL));
        seeded = 1;
    }
    return (double)rand() / ((double)RAND_MAX + 1.0);
}

static void append_to_buffer(char *buf, int bufsize, const char *text) {
    size_t used;
    size_t avail;

    if (bufsize <= 0 || !text) return;

    used = strlen(buf);
    if (used >= (size_t)bufsize - 1) return;

    avail = (size_t)bufsize - used;
    strncat(buf, text, avail - 1);
}

/* Convert value to string for output */
static void value_to_string(OfortInterpreter *I, OfortValue v, char *buf, int bufsize) {
    switch (v.type) {
        case FVAL_INTEGER:
            snprintf(buf, bufsize, "%lld", v.v.i);
            break;
        case FVAL_REAL:
            snprintf(buf, bufsize, "%.7g", v.v.r);
            break;
        case FVAL_DOUBLE:
            snprintf(buf, bufsize, "%.15g", v.v.r);
            break;
        case FVAL_COMPLEX:
            snprintf(buf, bufsize, "(%.7g,%.7g)", v.v.cx.re, v.v.cx.im);
            break;
        case FVAL_CHARACTER:
            snprintf(buf, bufsize, "%s", v.v.s ? v.v.s : "");
            break;
        case FVAL_LOGICAL:
            snprintf(buf, bufsize, "%s", v.v.b ? "T" : "F");
            break;
        case FVAL_ARRAY:
            buf[0] = '\0';
            if (!v.v.arr.allocated || !v.v.arr.data || v.v.arr.len <= 0) {
                break;
            }
            for (int i = 0; i < v.v.arr.len; i++) {
                char elem[1024];
                if (i > 0) append_to_buffer(buf, bufsize, " ");
                value_to_string(I, v.v.arr.data[i], elem, sizeof(elem));
                append_to_buffer(buf, bufsize, elem);
            }
            break;
        default:
            buf[0] = '\0';
            break;
    }
}

static const char *type_token_intrinsic_name(OfortTokenType t) {
    switch (t) {
        case FTOK_REAL: return "REAL";
        case FTOK_LOGICAL: return "LOGICAL";
        default: return NULL;
    }
}

static OfortUnitFile *find_unit_file(OfortInterpreter *I, int unit) {
    for (int i = 0; i < I->n_unit_files; i++) {
        if (I->unit_files[i].unit == unit) {
            return &I->unit_files[i];
        }
    }
    return NULL;
}

static void set_unit_file(OfortInterpreter *I, int unit, const char *path) {
    OfortUnitFile *entry = find_unit_file(I, unit);
    if (!entry) {
        if (I->n_unit_files >= 32) ofort_error(I, "Too many open units");
        entry = &I->unit_files[I->n_unit_files++];
        entry->unit = unit;
    }
    char trimmed[sizeof(entry->path)];
    size_t len = path ? strlen(path) : 0;
    while (len > 0 && path[len - 1] == ' ') len--;
    if (len >= sizeof(trimmed)) len = sizeof(trimmed) - 1;
    if (len > 0) memcpy(trimmed, path, len);
    trimmed[len] = '\0';
    copy_cstr(entry->path, sizeof(entry->path), trimmed);
    entry->path[sizeof(entry->path) - 1] = '\0';
    entry->stream_pos = 0;
}

static void remove_unit_file(OfortInterpreter *I, int unit) {
    for (int i = 0; i < I->n_unit_files; i++) {
        if (I->unit_files[i].unit == unit) {
            I->unit_files[i] = I->unit_files[I->n_unit_files - 1];
            I->n_unit_files--;
            return;
        }
    }
}

static void write_values_to_file(OfortInterpreter *I, const char *path, OfortValue *vals, int nvals) {
    FILE *fp = fopen(path, "w");
    if (!fp) ofort_error(I, "Cannot open '%s' for writing", path);
    for (int i = 0; i < nvals; i++) {
        char buf[4096];
        if (i > 0) fputc(' ', fp);
        value_to_string(I, vals[i], buf, sizeof(buf));
        fputs(buf, fp);
    }
    fputc('\n', fp);
    fclose(fp);
}

static void write_values_to_stream_file(OfortInterpreter *I, const char *path, OfortValue *vals, int nvals) {
    FILE *fp = fopen(path, "ab");
    if (!fp) ofort_error(I, "Cannot open '%s' for stream writing", path);
    for (int i = 0; i < nvals; i++) {
        if (vals[i].type == FVAL_ARRAY) {
            for (int j = 0; j < vals[i].v.arr.len; j++) {
                char buf[4096];
                value_to_string(I, vals[i].v.arr.data[j], buf, sizeof(buf));
                fprintf(fp, "%s\n", buf);
            }
        } else {
            char buf[4096];
            value_to_string(I, vals[i], buf, sizeof(buf));
            fprintf(fp, "%s\n", buf);
        }
    }
    fclose(fp);
}

static int read_next_token(FILE *fp, char *buf, int bufsize) {
    int c;
    int len = 0;

    do {
        c = fgetc(fp);
        if (c == EOF) return 0;
    } while (isspace(c));

    while (c != EOF && !isspace(c)) {
        if (len < bufsize - 1) {
            buf[len++] = (char)c;
        }
        c = fgetc(fp);
    }
    buf[len] = '\0';
    return 1;
}

static int read_next_string_token(const char **p, char *buf, int bufsize) {
    int len = 0;

    while (**p && isspace((unsigned char)**p)) {
        (*p)++;
    }
    if (!**p) {
        return 0;
    }
    while (**p && !isspace((unsigned char)**p)) {
        if (len < bufsize - 1) {
            buf[len++] = **p;
        }
        (*p)++;
    }
    buf[len] = '\0';
    return 1;
}

static void assign_token_to_value(OfortValue *dest, const char *token) {
    if (dest->type == FVAL_INTEGER) {
        dest->v.i = strtoll(token, NULL, 10);
    } else if (dest->type == FVAL_REAL || dest->type == FVAL_DOUBLE) {
        dest->v.r = strtod(token, NULL);
    } else if (dest->type == FVAL_CHARACTER) {
        free_value(dest);
        *dest = make_character(token);
    } else if (dest->type == FVAL_LOGICAL) {
        dest->v.b = token[0] == 'T' || token[0] == 't' || strcmp(token, ".true.") == 0;
    }
}

static int format_is_character_line_read(const char *fmt) {
    while (*fmt) {
        if (*fmt == 'a' || *fmt == 'A') {
            return 1;
        }
        fmt++;
    }
    return 0;
}

static void assign_line_to_character_target(OfortInterpreter *I, OfortNode *target, const char *line) {
    if (target->type != FND_IDENT) return;
    OfortVar *v = find_var(I, target->name);
    if (!v) ofort_error(I, "Undefined variable '%s'", target->name);
    if (v->val.type != FVAL_CHARACTER)
        ofort_error(I, "READ '(A)' target must be CHARACTER");
    free_value(&v->val);
    v->val = make_character(line ? line : "");
}

static void read_values_from_file(OfortInterpreter *I, const char *path, OfortNode *n) {
    FILE *fp = fopen(path, "r");
    char tok[1024];
    if (!fp) ofort_error(I, "Cannot open '%s' for reading", path);

    if (format_is_character_line_read(n->format_str) && n->n_stmts > 0) {
        char line[OFORT_MAX_STRLEN];
        if (!fgets(line, sizeof(line), fp)) line[0] = '\0';
        line[strcspn(line, "\r\n")] = '\0';
        assign_line_to_character_target(I, n->stmts[0], line);
        fclose(fp);
        return;
    }

    for (int i = 0; i < n->n_stmts; i++) {
        if (n->stmts[i]->type != FND_IDENT) continue;
        OfortVar *v = find_var(I, n->stmts[i]->name);
        if (!v) ofort_error(I, "Undefined variable '%s'", n->stmts[i]->name);
        if (v->val.type == FVAL_ARRAY) {
            for (int j = 0; j < v->val.v.arr.len; j++) {
                if (!read_next_token(fp, tok, sizeof(tok))) break;
                assign_token_to_value(&v->val.v.arr.data[j], tok);
            }
        } else {
            if (read_next_token(fp, tok, sizeof(tok))) {
                assign_token_to_value(&v->val, tok);
            }
        }
    }
    fclose(fp);
}

static void read_values_from_string(OfortInterpreter *I, const char *text, OfortNode *n) {
    const char *p = text ? text : "";
    char tok[1024];

    if (format_is_character_line_read(n->format_str) && n->n_stmts > 0) {
        assign_line_to_character_target(I, n->stmts[0], p);
        return;
    }

    for (int i = 0; i < n->n_stmts; i++) {
        if (n->stmts[i]->type != FND_IDENT) continue;
        OfortVar *v = find_var(I, n->stmts[i]->name);
        if (!v) ofort_error(I, "Undefined variable '%s'", n->stmts[i]->name);
        if (v->val.type == FVAL_ARRAY) {
            for (int j = 0; j < v->val.v.arr.len; j++) {
                if (!read_next_string_token(&p, tok, sizeof(tok))) break;
                assign_token_to_value(&v->val.v.arr.data[j], tok);
            }
        } else {
            if (read_next_string_token(&p, tok, sizeof(tok))) {
                assign_token_to_value(&v->val, tok);
            }
        }
    }
}

static int read_stream_token_at(FILE *fp, int *stream_pos, char *buf, int bufsize) {
    char line[1024];
    int current = 0;

    rewind(fp);
    while (fgets(line, sizeof(line), fp)) {
        if (current == *stream_pos) {
            line[strcspn(line, "\r\n")] = '\0';
            snprintf(buf, bufsize, "%s", line);
            (*stream_pos)++;
            return 1;
        }
        current++;
    }
    return 0;
}

static void read_values_from_stream_file(OfortInterpreter *I, OfortUnitFile *entry, OfortNode *n) {
    FILE *fp = fopen(entry->path, "rb");
    char tok[1024];
    if (!fp) ofort_error(I, "Cannot open '%s' for stream reading", entry->path);

    for (int i = 0; i < n->n_stmts; i++) {
        if (n->stmts[i]->type != FND_IDENT) continue;
        OfortVar *v = find_var(I, n->stmts[i]->name);
        if (!v) ofort_error(I, "Undefined variable '%s'", n->stmts[i]->name);
        if (v->val.type == FVAL_ARRAY) {
            for (int j = 0; j < v->val.v.arr.len; j++) {
                if (!read_stream_token_at(fp, &entry->stream_pos, tok, sizeof(tok))) break;
                assign_token_to_value(&v->val.v.arr.data[j], tok);
            }
        } else {
            if (read_stream_token_at(fp, &entry->stream_pos, tok, sizeof(tok))) {
                assign_token_to_value(&v->val, tok);
            }
        }
    }
    fclose(fp);
}

static void format_descriptors(OfortInterpreter *I, const char *p, const char *end,
                               OfortValue *vals, int nvals, int *vidx) {
    while (*p && (!end || p < end)) {
        int repeat = 1;
        char fc;

        if (nvals > 0 && *vidx >= nvals) break;

        while (*p == ' ' || *p == ',') p++;
        if (!*p || (end && p >= end) || *p == ')') break;

        if (*p == '*') {
            p++;
            while (*p == ' ') p++;
            if (*p == '(') {
                const char *group_start = p + 1;
                const char *q = group_start;
                int depth = 1;

                while (*q && depth > 0) {
                    if (*q == '(') depth++;
                    else if (*q == ')') depth--;
                    q++;
                }

                if (depth == 0) {
                    const char *group_end = q - 1;
                    while (*vidx < nvals) {
                        int before = *vidx;
                        format_descriptors(I, group_start, group_end, vals, nvals, vidx);
                        if (*vidx == before) break;
                    }
                    p = q;
                    continue;
                }
            }
            continue;
        }

        if (isdigit((unsigned char)*p)) {
            repeat = 0;
            while (isdigit((unsigned char)*p)) {
                repeat = repeat * 10 + (*p - '0');
                p++;
            }
        }

        if (*p == '(') {
            const char *group_start = p + 1;
            const char *q = group_start;
            int depth = 1;

            while (*q && depth > 0) {
                if (*q == '(') depth++;
                else if (*q == ')') depth--;
                q++;
            }

            if (depth == 0) {
                const char *group_end = q - 1;
                for (int r = 0; r < repeat; r++) {
                    format_descriptors(I, group_start, group_end, vals, nvals, vidx);
                }
                p = q;
                continue;
            }
        }

        fc = (char)toupper((unsigned char)*p);

        if (fc == 'A') {
            int width = 0;
            p++;
            while (isdigit((unsigned char)*p)) { width = width * 10 + (*p - '0'); p++; }
            for (int r = 0; r < repeat && *vidx < nvals; r++, (*vidx)++) {
                char buf[1024];
                value_to_string(I, vals[*vidx], buf, sizeof(buf));
                if (width > 0) {
                    int slen = (int)strlen(buf);
                    if (slen < width) {
                        char padded[1024];
                        memset(padded, ' ', width);
                        memcpy(padded + width - slen, buf, slen);
                        padded[width] = '\0';
                        out_append(I, padded);
                    } else {
                        buf[width] = '\0';
                        out_append(I, buf);
                    }
                } else {
                    out_append(I, buf);
                }
            }
        } else if (fc == 'I') {
            int width = 0, min_digits = 0;
            p++;
            while (isdigit((unsigned char)*p)) { width = width * 10 + (*p - '0'); p++; }
            if (*p == '.') { p++; while (isdigit((unsigned char)*p)) { min_digits = min_digits * 10 + (*p - '0'); p++; } }
            for (int r = 0; r < repeat && *vidx < nvals; r++, (*vidx)++) {
                char buf[64];
                long long iv = val_to_int(vals[*vidx]);
                if (min_digits > 0) {
                    char raw[64];
                    char padded[64];
                    int raw_len, zero_count, digit_len, pad_count, out_pos = 0;
                    unsigned long long mag = iv < 0 ? (unsigned long long)(-iv) : (unsigned long long)iv;
                    if (min_digits > 60) min_digits = 60;
                    if (width < 0) width = 0;
                    if (width > 60) width = 60;
                    snprintf(raw, sizeof(raw), "%llu", mag);
                    raw_len = (int)strlen(raw);
                    zero_count = min_digits > raw_len ? min_digits - raw_len : 0;
                    digit_len = zero_count + raw_len + (iv < 0 ? 1 : 0);
                    pad_count = width > digit_len ? width - digit_len : 0;
                    for (int k = 0; k < pad_count && out_pos < (int)sizeof(padded) - 1; k++) padded[out_pos++] = ' ';
                    if (iv < 0 && out_pos < (int)sizeof(padded) - 1) padded[out_pos++] = '-';
                    for (int k = 0; k < zero_count && out_pos < (int)sizeof(padded) - 1; k++) padded[out_pos++] = '0';
                    for (int k = 0; raw[k] && out_pos < (int)sizeof(padded) - 1; k++) padded[out_pos++] = raw[k];
                    padded[out_pos] = '\0';
                    copy_cstr(buf, sizeof(buf), padded);
                } else {
                    snprintf(buf, sizeof(buf), "%*lld", width, iv);
                }
                out_append(I, buf);
            }
        } else if (fc == 'F' || fc == 'E' || fc == 'D' || fc == 'G') {
            int width = 0, dec = 0;
            p++;
            while (isdigit((unsigned char)*p)) { width = width * 10 + (*p - '0'); p++; }
            if (*p == '.') { p++; while (isdigit((unsigned char)*p)) { dec = dec * 10 + (*p - '0'); p++; } }
            for (int r = 0; r < repeat && *vidx < nvals; r++, (*vidx)++) {
                double rv = val_to_real(vals[*vidx]);
                char buf[128];
                if (fc == 'F') snprintf(buf, sizeof(buf), "%*.*f", width, dec, rv);
                else if (fc == 'G') snprintf(buf, sizeof(buf), "%*.*g", width, dec, rv);
                else snprintf(buf, sizeof(buf), "%*.*E", width, dec, rv);
                out_append(I, buf);
            }
        } else if (fc == 'L') {
            int width = 0;
            p++;
            while (isdigit((unsigned char)*p)) { width = width * 10 + (*p - '0'); p++; }
            for (int r = 0; r < repeat && *vidx < nvals; r++, (*vidx)++) {
                int bv = val_to_logical(vals[*vidx]);
                char buf[64];
                if (width > 1) {
                    memset(buf, ' ', width - 1);
                    buf[width - 1] = bv ? 'T' : 'F';
                    buf[width] = '\0';
                } else {
                    buf[0] = bv ? 'T' : 'F';
                    buf[1] = '\0';
                }
                out_append(I, buf);
            }
        } else if (fc == 'X') {
            p++;
            for (int r = 0; r < repeat; r++) out_append(I, " ");
        } else if (fc == '/') {
            p++;
            for (int r = 0; r < repeat; r++) out_append(I, "\n");
        } else if (fc == '\'' || fc == '"') {
            char quote = *p++;
            while (*p && *p != quote) {
                char c[2] = {*p, '\0'};
                out_append(I, c);
                p++;
            }
            if (*p == quote) p++;
        } else {
            p++;
        }
    }
}

/* Format output using Fortran format descriptors */
static void format_output(OfortInterpreter *I, const char *fmt, OfortValue *vals, int nvals) {
    int flattened_count = 0;
    int needs_flatten = 0;
    for (int i = 0; i < nvals; i++) {
        if (vals[i].type == FVAL_ARRAY) {
            needs_flatten = 1;
            flattened_count += vals[i].v.arr.len;
        } else {
            flattened_count++;
        }
    }
    if (needs_flatten) {
        OfortValue *flat = (OfortValue *)calloc(flattened_count ? flattened_count : 1, sizeof(OfortValue));
        int k = 0;
        if (!flat) ofort_error(I, "Out of memory flattening output list");
        for (int i = 0; i < nvals; i++) {
            if (vals[i].type == FVAL_ARRAY) {
                for (int j = 0; j < vals[i].v.arr.len; j++) {
                    flat[k++] = copy_value(vals[i].v.arr.data[j]);
                }
            } else {
                flat[k++] = copy_value(vals[i]);
            }
        }
        format_output(I, fmt, flat, flattened_count);
        for (int i = 0; i < flattened_count; i++) free_value(&flat[i]);
        free(flat);
        return;
    }

    if (!fmt || !fmt[0]) {
        /* list-directed output */
        int i;
        for (i = 0; i < nvals; i++) {
            if (i > 0) out_append(I, " ");
            char buf[1024];
            value_to_string(I, vals[i], buf, sizeof(buf));
            out_append(I, buf);
        }
        out_append(I, "\n");
        return;
    }

    const char *p = fmt;
    const char *end = NULL;
    int vidx = 0;

    if (*p == '(') {
        int depth = 1;
        p++;
        end = p;
        while (*end && depth > 0) {
            if (*end == '(') depth++;
            else if (*end == ')') depth--;
            end++;
        }
        if (depth == 0) end--;
        else end = NULL;
    }

    do {
        format_descriptors(I, p, end, vals, nvals, &vidx);
        if (vidx < nvals) out_append(I, "\n");
    } while (vidx < nvals);
    out_append(I, "\n");
}

static void append_io_value(OfortInterpreter *I, OfortValue **vals, int *nvals, int *cap,
                            OfortValue val) {
    (void)I;
    if (*nvals >= *cap) {
        *cap = *cap ? *cap * 2 : 8;
        *vals = (OfortValue *)realloc(*vals, sizeof(OfortValue) * (size_t)*cap);
        if (!*vals) ofort_error(I, "Out of memory expanding I/O list");
    }
    (*vals)[(*nvals)++] = val;
}

static void collect_io_values(OfortInterpreter *I, OfortNode *node,
                              OfortValue **vals, int *nvals, int *cap) {
    if (node->type == FND_IMPLIED_DO) {
        OfortValue start_v = eval_node(I, node->children[0]);
        OfortValue end_v = eval_node(I, node->children[1]);
        OfortValue step_v = eval_node(I, node->children[2]);
        long long start = val_to_int(start_v);
        long long end = val_to_int(end_v);
        long long step = val_to_int(step_v);
        free_value(&start_v);
        free_value(&end_v);
        free_value(&step_v);
        if (step == 0) ofort_error(I, "Implied DO step cannot be zero");
        for (long long iter = start; step > 0 ? iter <= end : iter >= end; iter += step) {
            set_var(I, node->name, make_integer(iter));
            for (int i = 0; i < node->n_stmts; i++) {
                collect_io_values(I, node->stmts[i], vals, nvals, cap);
            }
        }
        return;
    }

    append_io_value(I, vals, nvals, cap, eval_node(I, node));
}

static OfortValue *eval_io_list(OfortInterpreter *I, OfortNode *n, int *nvals_out) {
    OfortValue *vals = NULL;
    int nvals = 0;
    int cap = 0;
    for (int i = 0; i < n->n_stmts; i++) {
        collect_io_values(I, n->stmts[i], &vals, &nvals, &cap);
    }
    if (!vals) vals = (OfortValue *)calloc(1, sizeof(OfortValue));
    *nvals_out = nvals;
    return vals;
}

/* Arithmetic promotion */
static int needs_real_promotion(OfortValue a, OfortValue b) {
    return (a.type == FVAL_REAL || a.type == FVAL_DOUBLE ||
            b.type == FVAL_REAL || b.type == FVAL_DOUBLE);
}

static int needs_complex_promotion(OfortValue a, OfortValue b) {
    return (a.type == FVAL_COMPLEX || b.type == FVAL_COMPLEX);
}

/* Evaluate expression node */
static OfortValue eval_node(OfortInterpreter *I, OfortNode *n) {
    if (!n) return make_void_val();
    if (n->line > 0) I->current_line = n->line;

    switch (n->type) {
    case FND_INT_LIT:
        return make_integer_kind(n->int_val, n->kind);

    case FND_REAL_LIT:
        if (n->val_type == FVAL_DOUBLE) return make_double(n->num_val);
        return make_real(n->num_val);

    case FND_STRING_LIT:
        return make_character(n->str_val);

    case FND_LOGICAL_LIT:
        return make_logical(n->bool_val);

    case FND_COMPLEX_LIT: {
        OfortValue re_val = eval_node(I, n->children[0]);
        OfortValue im_val = eval_node(I, n->children[1]);
        int kind = (re_val.type == FVAL_DOUBLE || re_val.kind == 8 ||
                    im_val.type == FVAL_DOUBLE || im_val.kind == 8) ? 8 : 4;
        double re = val_to_real(re_val);
        double im = val_to_real(im_val);
        return make_complex_kind(re, im, kind);
    }

    case FND_IDENT: {
        OfortVar *v = find_var(I, n->name);
        if (!v) ofort_error(I, "Undefined variable '%s' at line %d", n->name, n->line);
        if (v->is_pointer) {
            if (!v->pointer_associated) return make_void_val();
            return copy_value(v->val);
        }
        return copy_value(v->val);
    }

    case FND_NEGATE: {
        OfortValue v = eval_node(I, n->children[0]);
        switch (v.type) {
            case FVAL_INTEGER: v.v.i = -v.v.i; break;
            case FVAL_REAL: case FVAL_DOUBLE: v.v.r = -v.v.r; break;
            case FVAL_COMPLEX: v.v.cx.re = -v.v.cx.re; v.v.cx.im = -v.v.cx.im; break;
            default: ofort_error(I, "Cannot negate this type");
        }
        return v;
    }

    case FND_NOT: {
        OfortValue v = eval_node(I, n->children[0]);
        return make_logical(!val_to_logical(v));
    }

    case FND_ADD: case FND_SUB: case FND_MUL: case FND_DIV: case FND_POWER: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);

        /* Array operations: element-wise */
        if (left.type == FVAL_ARRAY || right.type == FVAL_ARRAY) {
            OfortValue arr_op;
            OfortValue scalar;
            int arr_len;
            if (left.type == FVAL_ARRAY && right.type == FVAL_ARRAY) {
                /* array op array */
                if (left.v.arr.len != right.v.arr.len)
                    ofort_error(I, "Array size mismatch in operation");
                arr_op = copy_value(left);
                for (int i = 0; i < left.v.arr.len; i++) {
                    OfortValue lv = left.v.arr.data[i];
                    OfortValue rv = right.v.arr.data[i];
                    double a = val_to_real(lv), b = val_to_real(rv);
                    double res;
                    switch (n->type) {
                        case FND_ADD: res = a + b; break;
                        case FND_SUB: res = a - b; break;
                        case FND_MUL: res = a * b; break;
                        case FND_DIV: res = b != 0 ? a / b : 0; break;
                        case FND_POWER: res = pow(a, b); break;
                        default: res = 0; break;
                    }
                    free_value(&arr_op.v.arr.data[i]);
                    if (arr_op.v.arr.elem_type == FVAL_INTEGER)
                        arr_op.v.arr.data[i] = make_integer((long long)res);
                    else
                        arr_op.v.arr.data[i] = make_real(res);
                }
                free_value(&left); free_value(&right);
                return arr_op;
            }
            /* array op scalar or scalar op array */
            if (left.type == FVAL_ARRAY) {
                arr_op = copy_value(left); scalar = right; arr_len = left.v.arr.len;
            } else {
                arr_op = copy_value(right); scalar = left; arr_len = right.v.arr.len;
            }
            double sv = val_to_real(scalar);
            for (int i = 0; i < arr_len; i++) {
                double ev = val_to_real(arr_op.v.arr.data[i]);
                double res;
                if (left.type == FVAL_ARRAY) {
                    switch (n->type) {
                        case FND_ADD: res = ev + sv; break;
                        case FND_SUB: res = ev - sv; break;
                        case FND_MUL: res = ev * sv; break;
                        case FND_DIV: res = sv != 0 ? ev / sv : 0; break;
                        case FND_POWER: res = pow(ev, sv); break;
                        default: res = 0; break;
                    }
                } else {
                    switch (n->type) {
                        case FND_ADD: res = sv + ev; break;
                        case FND_SUB: res = sv - ev; break;
                        case FND_MUL: res = sv * ev; break;
                        case FND_DIV: res = ev != 0 ? sv / ev : 0; break;
                        case FND_POWER: res = pow(sv, ev); break;
                        default: res = 0; break;
                    }
                }
                free_value(&arr_op.v.arr.data[i]);
                if (arr_op.v.arr.elem_type == FVAL_INTEGER)
                    arr_op.v.arr.data[i] = make_integer((long long)res);
                else
                    arr_op.v.arr.data[i] = make_real(res);
            }
            free_value(&left); free_value(&right);
            return arr_op;
        }

        /* Complex arithmetic */
        if (needs_complex_promotion(left, right)) {
            double lre, lim, rre, rim;
            if (left.type == FVAL_COMPLEX) { lre = left.v.cx.re; lim = left.v.cx.im; }
            else { lre = val_to_real(left); lim = 0; }
            if (right.type == FVAL_COMPLEX) { rre = right.v.cx.re; rim = right.v.cx.im; }
            else { rre = val_to_real(right); rim = 0; }
            double re, im;
            switch (n->type) {
                case FND_ADD: re = lre + rre; im = lim + rim; break;
                case FND_SUB: re = lre - rre; im = lim - rim; break;
                case FND_MUL: re = lre*rre - lim*rim; im = lre*rim + lim*rre; break;
                case FND_DIV: {
                    double d = rre*rre + rim*rim;
                    if (d == 0) ofort_error(I, "Division by zero");
                    re = (lre*rre + lim*rim) / d;
                    im = (lim*rre - lre*rim) / d;
                    break;
                }
                default: re = 0; im = 0; break;
            }
            free_value(&left); free_value(&right);
            return make_complex(re, im);
        }

        /* Real/Double arithmetic */
        if (needs_real_promotion(left, right) || n->type == FND_POWER) {
            double a = val_to_real(left), b = val_to_real(right);
            double res;
            switch (n->type) {
                case FND_ADD: res = a + b; break;
                case FND_SUB: res = a - b; break;
                case FND_MUL: res = a * b; break;
                case FND_DIV:
                    if (b == 0.0) ofort_error(I, "Division by zero");
                    res = a / b; break;
                case FND_POWER: res = pow(a, b); break;
                default: res = 0; break;
            }
            free_value(&left); free_value(&right);
            if (left.type == FVAL_DOUBLE || right.type == FVAL_DOUBLE)
                return make_double(res);
            /* For POWER with integer operands, return integer if both are integers */
            if (n->type == FND_POWER && left.type == FVAL_INTEGER && right.type == FVAL_INTEGER)
                return make_integer((long long)res);
            return make_real(res);
        }

        /* Integer arithmetic */
        {
            long long a = val_to_int(left), b = val_to_int(right);
            long long res;
            switch (n->type) {
                case FND_ADD: res = a + b; break;
                case FND_SUB: res = a - b; break;
                case FND_MUL: res = a * b; break;
                case FND_DIV:
                    if (b == 0) ofort_error(I, "Division by zero");
                    res = a / b; break;
                default: res = 0; break;
            }
            free_value(&left); free_value(&right);
            return make_integer(res);
        }
    }

    case FND_CONCAT: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        char buf[OFORT_MAX_STRLEN * 2];
        char lbuf[OFORT_MAX_STRLEN], rbuf[OFORT_MAX_STRLEN];
        value_to_string(I, left, lbuf, sizeof(lbuf));
        value_to_string(I, right, rbuf, sizeof(rbuf));
        snprintf(buf, sizeof(buf), "%s%s", lbuf, rbuf);
        free_value(&left); free_value(&right);
        return make_character(buf);
    }

    /* Comparison operators */
    case FND_EQ: case FND_NEQ: case FND_LT: case FND_GT: case FND_LE: case FND_GE: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        int result = 0;

        if (left.type == FVAL_ARRAY || right.type == FVAL_ARRAY) {
            OfortValue *array_arg = left.type == FVAL_ARRAY ? &left : &right;
            OfortValue result_array = make_array(FVAL_LOGICAL, array_arg->v.arr.dims, array_arg->v.arr.n_dims);
            int len = array_arg->v.arr.len;

            if (left.type == FVAL_ARRAY && right.type == FVAL_ARRAY && left.v.arr.len != right.v.arr.len)
                ofort_error(I, "Array size mismatch in comparison");

            for (int i = 0; i < len; i++) {
                OfortValue *lv = left.type == FVAL_ARRAY ? &left.v.arr.data[i] : &left;
                OfortValue *rv = right.type == FVAL_ARRAY ? &right.v.arr.data[i] : &right;
                int elem_result = 0;
                if (lv->type == FVAL_CHARACTER || rv->type == FVAL_CHARACTER) {
                    char lb[OFORT_MAX_STRLEN], rb[OFORT_MAX_STRLEN];
                    value_to_string(I, *lv, lb, sizeof(lb));
                    value_to_string(I, *rv, rb, sizeof(rb));
                    int cmp = strcmp(lb, rb);
                    switch (n->type) {
                        case FND_EQ: elem_result = (cmp == 0); break;
                        case FND_NEQ: elem_result = (cmp != 0); break;
                        case FND_LT: elem_result = (cmp < 0); break;
                        case FND_GT: elem_result = (cmp > 0); break;
                        case FND_LE: elem_result = (cmp <= 0); break;
                        case FND_GE: elem_result = (cmp >= 0); break;
                        default: break;
                    }
                } else {
                    double a = val_to_real(*lv), b = val_to_real(*rv);
                    switch (n->type) {
                        case FND_EQ: elem_result = (a == b); break;
                        case FND_NEQ: elem_result = (a != b); break;
                        case FND_LT: elem_result = (a < b); break;
                        case FND_GT: elem_result = (a > b); break;
                        case FND_LE: elem_result = (a <= b); break;
                        case FND_GE: elem_result = (a >= b); break;
                        default: break;
                    }
                }
                free_value(&result_array.v.arr.data[i]);
                result_array.v.arr.data[i] = make_logical(elem_result);
            }
            free_value(&left); free_value(&right);
            return result_array;
        }

        if (left.type == FVAL_CHARACTER || right.type == FVAL_CHARACTER) {
            char lb[OFORT_MAX_STRLEN], rb[OFORT_MAX_STRLEN];
            value_to_string(I, left, lb, sizeof(lb));
            value_to_string(I, right, rb, sizeof(rb));
            int cmp = strcmp(lb, rb);
            switch (n->type) {
                case FND_EQ: result = (cmp == 0); break;
                case FND_NEQ: result = (cmp != 0); break;
                case FND_LT: result = (cmp < 0); break;
                case FND_GT: result = (cmp > 0); break;
                case FND_LE: result = (cmp <= 0); break;
                case FND_GE: result = (cmp >= 0); break;
                default: break;
            }
        } else {
            double a = val_to_real(left), b = val_to_real(right);
            switch (n->type) {
                case FND_EQ: result = (a == b); break;
                case FND_NEQ: result = (a != b); break;
                case FND_LT: result = (a < b); break;
                case FND_GT: result = (a > b); break;
                case FND_LE: result = (a <= b); break;
                case FND_GE: result = (a >= b); break;
                default: break;
            }
        }
        free_value(&left); free_value(&right);
        return make_logical(result);
    }

    case FND_AND: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        int result = val_to_logical(left) && val_to_logical(right);
        free_value(&left); free_value(&right);
        return make_logical(result);
    }
    case FND_OR: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        int result = val_to_logical(left) || val_to_logical(right);
        free_value(&left); free_value(&right);
        return make_logical(result);
    }
    case FND_EQV: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        int result = val_to_logical(left) == val_to_logical(right);
        free_value(&left); free_value(&right);
        return make_logical(result);
    }
    case FND_NEQV: {
        OfortValue left = eval_node(I, n->children[0]);
        OfortValue right = eval_node(I, n->children[1]);
        int result = val_to_logical(left) != val_to_logical(right);
        free_value(&left); free_value(&right);
        return make_logical(result);
    }

    case FND_FUNC_CALL: {
        /* Could be function call, array reference, or type constructor */
        /* Evaluate arguments */
        int nargs = n->n_stmts;
        OfortValue args[OFORT_MAX_PARAMS];

        if (str_eq_nocase(n->name, "associated")) {
            OfortVar *ptr;
            if (nargs < 1 || n->stmts[0]->type != FND_IDENT)
                ofort_error(I, "ASSOCIATED requires a pointer argument");
            ptr = find_var(I, n->stmts[0]->name);
            if (!ptr || !ptr->is_pointer) return make_logical(0);
            if (nargs == 1) return make_logical(ptr->pointer_associated);
            return make_logical(pointer_matches_target(I, ptr, n->stmts[1]));
        }

        /* Check if this is an array variable reference */
        OfortVar *var = find_var(I, n->name);
        if (var && var->val.type == FVAL_ARRAY) {
            return eval_array_section(I, var, n);
        }

        if (str_eq_nocase(n->name, "present")) {
            int present = 0;
            if (nargs != 1 || n->stmts[0]->type != FND_IDENT) {
                ofort_error(I, "PRESENT requires one dummy argument name");
            }
            var = find_var(I, n->stmts[0]->name);
            present = var && var->present;
            return make_logical(present);
        }

        /* Evaluate all args */
        for (int i = 0; i < nargs; i++) args[i] = eval_node(I, n->stmts[i]);

        /* Check for intrinsic */
        if (is_intrinsic(n->name)) {
            OfortValue result = call_intrinsic(I, n->name, args, nargs, n->param_names);
            for (int i = 0; i < nargs; i++) free_value(&args[i]);
            return result;
        }

        /* Check for user function */
        OfortFunc *func = find_func(I, n->name);
        if (func && func->is_function) {
            OfortNode *fn = func->node;
            push_scope(I);
            /* Bind parameters */
            for (int i = 0; i < fn->n_params; i++) {
                if (i < nargs && args[i].type != FVAL_VOID) {
                    declare_var(I, fn->param_names[i], copy_value(args[i]));
                } else if (fn->param_optional[i]) {
                    declare_absent_optional_var(I, fn->param_names[i]);
                } else {
                    ofort_error(I, "Missing required argument '%s' in call to '%s'",
                                fn->param_names[i], fn->name);
                }
            }
            restore_saved_vars(I, func);
            /* Set up result variable */
            const char *res_name = fn->result_name[0] ? fn->result_name : fn->name;
            declare_var(I, res_name, default_value(fn->val_type, 1));

            /* Execute body */
            I->procedure_depth++;
            exec_node(I, fn->children[0]);
            I->procedure_depth--;
            I->returning = 0;

            /* Get result */
            OfortVar *rv = find_var(I, res_name);
            OfortValue result = rv ? copy_value(rv->val) : make_void_val();

            /* Handle INTENT(OUT/INOUT) — copy back */
            for (int i = 0; i < fn->n_params && i < nargs; i++) {
                if (fn->param_intents[i] == 2 || fn->param_intents[i] == 3) {
                    OfortVar *pv = find_var(I, fn->param_names[i]);
                    if (pv && pv->present && n->stmts[i]->type == FND_IDENT) {
                        free_value(&args[i]);
                        args[i] = copy_value(pv->val);
                    }
                }
            }

            store_saved_vars(func, I->current_scope);
            pop_scope(I);

            /* Write back OUT/INOUT args */
            for (int i = 0; i < fn->n_params && i < nargs; i++) {
                if (fn->param_intents[i] == 2 || fn->param_intents[i] == 3) {
                    if (n->stmts[i]->type == FND_IDENT && args[i].type != FVAL_VOID) {
                        set_var(I, n->stmts[i]->name, copy_value(args[i]));
                    }
                }
            }

            for (int i = 0; i < nargs; i++) free_value(&args[i]);
            return result;
        }

        /* Check for type constructor: TypeName(field1, field2, ...) */
        OfortTypeDef *td = find_type_def(I, n->name);
        if (td) {
            OfortValue v; memset(&v, 0, sizeof(v));
            v.type = FVAL_DERIVED;
            v.v.dt.n_fields = td->n_fields;
            v.v.dt.fields = (OfortValue *)calloc(td->n_fields, sizeof(OfortValue));
            v.v.dt.field_names = (char(*)[64])calloc(td->n_fields, sizeof(char[64]));
            copy_cstr(v.v.dt.type_name, sizeof(v.v.dt.type_name), td->name);
            for (int i = 0; i < td->n_fields; i++) {
                strcpy(v.v.dt.field_names[i], td->field_names[i]);
                if (i < nargs)
                    v.v.dt.fields[i] = copy_value(args[i]);
                else
                    v.v.dt.fields[i] = default_value(td->field_types[i], td->field_char_lens[i]);
            }
            for (int i = 0; i < nargs; i++) free_value(&args[i]);
            return v;
        }

        for (int i = 0; i < nargs; i++) free_value(&args[i]);
        ofort_error(I, "Unknown function or array '%s' at line %d", n->name, n->line);
        return make_void_val();
    }

    case FND_MEMBER: {
        OfortValue obj = eval_node(I, n->children[0]);
        if (str_eq_nocase(n->name, "re") || str_eq_nocase(n->name, "im")) {
            int want_re = str_eq_nocase(n->name, "re");
            if (obj.type == FVAL_COMPLEX) {
                double part = want_re ? obj.v.cx.re : obj.v.cx.im;
                free_value(&obj);
                return make_real(part);
            }
            if (obj.type == FVAL_ARRAY && obj.v.arr.elem_type == FVAL_COMPLEX) {
                OfortValue result = make_array(FVAL_REAL, obj.v.arr.dims, obj.v.arr.n_dims);
                for (int i = 0; i < obj.v.arr.len; i++) {
                    double part = 0.0;
                    if (obj.v.arr.data[i].type == FVAL_COMPLEX)
                        part = want_re ? obj.v.arr.data[i].v.cx.re : obj.v.arr.data[i].v.cx.im;
                    free_value(&result.v.arr.data[i]);
                    result.v.arr.data[i] = make_real(part);
                }
                free_value(&obj);
                return result;
            }
        }
        if (obj.type != FVAL_DERIVED)
            ofort_error(I, "Cannot access member of non-derived type");
        char upper[256];
        str_upper(upper, n->name, 256);
        for (int i = 0; i < obj.v.dt.n_fields; i++) {
            char fu[256];
            str_upper(fu, obj.v.dt.field_names[i], 256);
            if (strcmp(upper, fu) == 0) {
                OfortValue result = copy_value(obj.v.dt.fields[i]);
                free_value(&obj);
                return result;
            }
        }
        ofort_error(I, "Unknown member '%s'", n->name);
        return make_void_val();
    }

    case FND_ARRAY_CONSTRUCTOR: {
        int nelem = n->n_stmts;
        int dims[1] = {nelem};
        /* determine element type from first element */
        OfortValType etype = FVAL_INTEGER;
        OfortValue *elems = (OfortValue *)calloc(nelem, sizeof(OfortValue));
        for (int i = 0; i < nelem; i++) {
            elems[i] = eval_node(I, n->stmts[i]);
            if (i == 0) etype = elems[i].type;
        }
        OfortValue arr = make_array(etype, dims, 1);
        for (int i = 0; i < nelem; i++) {
            free_value(&arr.v.arr.data[i]);
            arr.v.arr.data[i] = elems[i];
        }
        free(elems);
        return arr;
    }

    case FND_SLICE:
        /* Should not be evaluated directly; handled in FUNC_CALL/ARRAY_REF */
        return make_void_val();

    default:
        ofort_error(I, "Cannot evaluate node type %d", n->type);
        return make_void_val();
    }
}

static void annotate_procedure_params(OfortNode *n) {
    OfortNode *body = n ? n->children[0] : NULL;
    if (!body) return;

    for (int i = 0; i < body->n_stmts; i++) {
        OfortNode *s = body->stmts[i];
        OfortNode **decls = &s;
        int n_decls = 1;
        if (s->type == FND_BLOCK) {
            decls = s->stmts;
            n_decls = s->n_stmts;
        }
        for (int j = 0; j < n_decls; j++) {
            OfortNode *d = decls[j];
            if (d->type != FND_VARDECL || (d->intent == 0 && !d->is_optional)) {
                continue;
            }
            for (int k = 0; k < n->n_params; k++) {
                if (str_eq_nocase(d->name, n->param_names[k])) {
                    n->param_intents[k] = d->intent;
                    n->param_types[k] = d->val_type;
                    n->param_optional[k] = d->is_optional;
                    break;
                }
            }
        }
    }
}

/* Execute statement node */
static void exec_node(OfortInterpreter *I, OfortNode *n) {
    int profile_line = 0;
    double profile_start = 0.0;
    if (!n) return;
    if (I->returning || I->exiting || I->cycling || I->stopping) return;
    if (n->line > 0) I->current_line = n->line;
    if (I->line_profile_enabled && node_is_profiled_statement(n)) {
        profile_line = n->line;
        profile_start = ofort_monotonic_seconds();
    }

    switch (n->type) {
    case FND_BLOCK: {
        int i;
        for (i = 0; i < n->n_stmts; i++) {
            exec_node(I, n->stmts[i]);
            if (I->returning || I->exiting || I->cycling || I->stopping) break;
        }
        break;
    }

    case FND_PROGRAM: {
        push_scope(I);
        exec_node(I, n->children[0]);
        pop_scope(I);
        break;
    }

    case FND_MODULE: {
        /* Register module: execute declarations, collect functions */
        if (I->n_modules >= OFORT_MAX_MODULES) ofort_error(I, "Too many modules");
        OfortModule *mod = &I->modules[I->n_modules++];
        char public_names[OFORT_MAX_PARAMS][256];
        char private_names[OFORT_MAX_PARAMS][256];
        int n_public_names = 0;
        int n_private_names = 0;
        copy_cstr(mod->name, sizeof(mod->name), n->name);
        mod->n_funcs = 0;
        mod->n_vars = 0;
        mod->n_types = 0;
        mod->default_private = 0;

        /* Execute the module body to register functions and declarations */
        push_scope(I);
        OfortNode *body = n->children[0];
        if (body) {
            for (int i = 0; i < body->n_stmts; i++) {
                OfortNode *s = body->stmts[i];
                if (s->type != FND_ACCESS) continue;
                if (s->n_params == 0) {
                    mod->default_private = s->bool_val ? 0 : 1;
                    continue;
                }
                for (int j = 0; j < s->n_params; j++) {
                    if (s->bool_val) {
                        if (n_public_names < OFORT_MAX_PARAMS)
                            copy_cstr(public_names[n_public_names++], sizeof(public_names[0]), s->param_names[j]);
                    } else {
                        if (n_private_names < OFORT_MAX_PARAMS)
                            copy_cstr(private_names[n_private_names++], sizeof(private_names[0]), s->param_names[j]);
                    }
                }
            }
            for (int i = 0; i < body->n_stmts; i++) {
                OfortNode *s = body->stmts[i];
                if (s->type == FND_ACCESS) {
                    continue;
                } else if (s->type == FND_SUBROUTINE || s->type == FND_FUNCTION) {
                    annotate_procedure_params(s);
                    register_func(I, s->name, s, s->type == FND_FUNCTION);
                } else if (s->type == FND_TYPE_DEF) {
                    exec_node(I, s);
                } else {
                    exec_node(I, s);
                }
            }
            /* Copy module variables */
            OfortScope *ms = I->current_scope;
            for (int i = 0; i < ms->n_vars && i < OFORT_MAX_VARS; i++) {
                int is_public = mod->default_private ? 0 : 1;
                if (name_in_list_nocase(ms->vars[i].name, public_names, n_public_names)) is_public = 1;
                if (name_in_list_nocase(ms->vars[i].name, private_names, n_private_names)) is_public = 0;
                mod->var_public[mod->n_vars] = is_public;
                mod->vars[mod->n_vars++] = ms->vars[i];
                ms->vars[i].val = make_void_val(); /* prevent double-free */
            }
        }
        pop_scope(I);
        break;
    }

    case FND_USE: {
        /* Import module variables and functions into current scope */
        char upper[256];
        str_upper(upper, n->name, 256);
        OfortModule *mod = NULL;
        for (int i = 0; i < I->n_modules; i++) {
            char mu[256];
            str_upper(mu, I->modules[i].name, 256);
            if (strcmp(upper, mu) == 0) { mod = &I->modules[i]; break; }
        }
        if (!mod) {
            if (strcmp(upper, "ISO_FORTRAN_ENV") == 0) {
                declare_var(I, "output_unit", make_integer(6));
                declare_var(I, "input_unit", make_integer(5));
                declare_var(I, "error_unit", make_integer(0));
                declare_var(I, "real64", make_integer(8));
                declare_var(I, "int64", make_integer(8));
                break;
            }
            if (strcmp(upper, "IEEE_ARITHMETIC") == 0) {
                break;
            }
            ofort_error(I, "Module '%s' not found", n->name);
        }
        /* import variables */
        for (int i = 0; i < mod->n_vars; i++) {
            if (!mod->var_public[i]) continue;
            OfortVar *v = declare_var(I, mod->vars[i].name, copy_value(mod->vars[i].val));
            v->is_protected = mod->vars[i].is_protected;
        }
        break;
    }

    case FND_TYPE_DEF: {
        /* Register type definition */
        if (I->n_type_defs >= 64) ofort_error(I, "Too many type definitions");
        OfortTypeDef *td = &I->type_defs[I->n_type_defs++];
        copy_cstr(td->name, sizeof(td->name), n->name);
        td->n_fields = 0;
        /* Parse field declarations from stmts */
        for (int i = 0; i < n->n_stmts; i++) {
            OfortNode *s = n->stmts[i];
            if (s->type == FND_BLOCK) {
                /* declaration block */
                for (int j = 0; j < s->n_stmts; j++) {
                    OfortNode *d = s->stmts[j];
                    if ((d->type == FND_VARDECL || d->type == FND_PARAMDECL) && td->n_fields < OFORT_MAX_FIELDS) {
                        copy_cstr(td->field_names[td->n_fields], sizeof(td->field_names[td->n_fields]), d->name);
                        td->field_types[td->n_fields] = d->val_type;
                        td->field_char_lens[td->n_fields] = d->char_len;
                        td->n_fields++;
                    }
                }
            } else if ((s->type == FND_VARDECL || s->type == FND_PARAMDECL) && td->n_fields < OFORT_MAX_FIELDS) {
                copy_cstr(td->field_names[td->n_fields], sizeof(td->field_names[td->n_fields]), s->name);
                td->field_types[td->n_fields] = s->val_type;
                td->field_char_lens[td->n_fields] = s->char_len;
                td->n_fields++;
            }
        }
        break;
    }

    case FND_IMPLICIT_NONE:
        if (I->current_scope) {
            if (n->bool_val) {
                I->current_scope->implicit_none = 1;
                memset(I->current_scope->implicit_types, 0, sizeof(I->current_scope->implicit_types));
            } else {
                I->current_scope->implicit_none = 0;
                for (int i = 0; i < 26; i++) {
                    if (n->implicit_types[i]) I->current_scope->implicit_types[i] = n->implicit_types[i];
                }
            }
        }
        break;

    case FND_VARDECL:
    case FND_PARAMDECL: {
        OfortValue val;
        int decl_char_len = n->val_type == FVAL_CHARACTER ? eval_character_length(I, n) : 0;
        OfortVar *existing = find_var(I, n->name);
        if (existing && (n->is_save || (I->procedure_depth > 0 && n->is_implicit_save))) {
            existing->is_save = 1;
            existing->is_implicit_save = n->is_implicit_save;
            existing->is_protected = n->is_protected;
            if (n->val_type == FVAL_CHARACTER) existing->char_len = decl_char_len;
            break;
        }
        if (existing && n->n_dims > 0) {
            int has_assumed_shape = 0;
            for (int i = 0; i < n->n_dims; i++) {
                if (n->dims[i] == 0) { has_assumed_shape = 1; break; }
            }
            if (has_assumed_shape) {
                existing->intent = n->intent;
                existing->is_pointer = n->is_pointer;
                existing->is_target = n->is_target;
                break;
            }
        }
        if (existing && (n->intent != 0 || n->is_optional)) {
            existing->intent = n->intent;
            if (n->val_type == FVAL_CHARACTER) existing->char_len = decl_char_len;
            break;
        }
        if (existing && n->type == FND_PARAMDECL && n->n_children > 0 && n->children[0]) {
            val = eval_node(I, n->children[0]);
            val = coerce_assignment_value(I, n->name, existing->val.type, val);
            val = resize_character_value(val, existing->char_len);
            free_value(&existing->val);
            existing->val = val;
            existing->is_parameter = 1;
            break;
        }
        if (n->is_pointer && n->n_dims > 0) {
            val.type = FVAL_ARRAY;
            memset(&val.v.arr, 0, sizeof(val.v.arr));
            val.v.arr.elem_type = n->val_type;
            val.v.arr.allocated = 0;
        } else if (n->n_dims > 0 && !n->is_allocatable) {
            /* Array declaration */
            val = make_array_from_decl(I, n);
        } else if (n->is_allocatable) {
            /* Allocatable: create empty array placeholder */
            val.type = FVAL_ARRAY;
            memset(&val.v.arr, 0, sizeof(val.v.arr));
            val.v.arr.elem_type = n->val_type;
            val.v.arr.allocated = 0;
        } else if (n->n_children > 0 && n->children[0]) {
            val = eval_node(I, n->children[0]);
        } else {
            val = default_value(n->val_type, n->val_type == FVAL_CHARACTER ? decl_char_len : n->char_len);
        }

        if (n->val_type == FVAL_CHARACTER)
            val = resize_character_value(val, decl_char_len);

        /* If there's an initializer and it's an array, set elements */
        if (n->n_dims > 0 && !n->is_allocatable && n->n_children > 0 && n->children[0]) {
            OfortValue init = eval_node(I, n->children[0]);
            if (init.type == FVAL_ARRAY) {
                /* copy elements */
                int count = init.v.arr.len < val.v.arr.len ? init.v.arr.len : val.v.arr.len;
                for (int i = 0; i < count; i++) {
                    OfortValue elem = copy_value(init.v.arr.data[i]);
                    if (val.v.arr.elem_type == FVAL_CHARACTER)
                        elem = resize_character_value(elem, decl_char_len);
                    free_value(&val.v.arr.data[i]);
                    val.v.arr.data[i] = elem;
                }
            }
            free_value(&init);
        }

        OfortVar *v = declare_var(I, n->name, val);
        if (n->is_parameter || n->type == FND_PARAMDECL) v->is_parameter = 1;
        v->is_allocatable = n->is_allocatable;
        v->is_pointer = n->is_pointer;
        v->is_target = n->is_target;
        v->is_protected = n->is_protected;
        v->is_save = n->is_save || (I->procedure_depth > 0 && n->is_implicit_save);
        v->is_implicit_save = I->procedure_depth > 0 && n->is_implicit_save;
        if (v->is_implicit_save) {
            ofort_warning(I, n->line,
                          "warning: local variable '%s' has implicit SAVE due to initialization",
                          n->name);
        }
        v->pointer_associated = 0;
        v->pointer_target[0] = '\0';
        v->pointer_has_slice = 0;
        v->pointer_slice_start = 0;
        v->pointer_slice_end = 0;
        v->intent = n->intent;
        v->char_len = decl_char_len;
        break;
    }

    case FND_POINTER_ASSIGN: {
        OfortNode *lhs = n->children[0];
        OfortNode *rhs_node = n->children[1];
        OfortVar *ptr;
        char target_name[256];
        int has_slice, slice_start, slice_end;
        OfortValue rhs;
        if (lhs->type != FND_IDENT)
            ofort_error(I, "Pointer assignment target must be a pointer variable");
        ptr = find_var(I, lhs->name);
        if (!ptr || !ptr->is_pointer)
            ofort_error(I, "'%s' is not a pointer", lhs->name);
        if (!pointer_target_descriptor(I, rhs_node, target_name, sizeof(target_name),
                                       &has_slice, &slice_start, &slice_end))
            ofort_error(I, "Invalid pointer target");
        rhs = eval_node(I, rhs_node);
        free_value(&ptr->val);
        ptr->val = rhs;
        ptr->pointer_associated = 1;
        copy_cstr(ptr->pointer_target, sizeof(ptr->pointer_target), target_name);
        ptr->pointer_has_slice = has_slice;
        ptr->pointer_slice_start = slice_start;
        ptr->pointer_slice_end = slice_end;
        break;
    }

    case FND_ASSIGN: {
        OfortNode *lhs = n->children[0];
        OfortValue rhs = eval_node(I, n->children[1]);

        if (lhs->type == FND_IDENT) {
            /* Simple variable assignment */
            OfortVar *v = find_var(I, lhs->name);
            if (v && v->is_parameter) ofort_error(I, "Cannot assign to PARAMETER '%s'", lhs->name);
            if (v && v->is_protected) ofort_error(I, "Cannot assign to PROTECTED variable '%s'", lhs->name);
            if (v && v->val.type == FVAL_ARRAY) {
                if (rhs.type == FVAL_ARRAY) {
                    if (!v->val.v.arr.allocated || v->val.v.arr.len == 0 ||
                        (v->is_allocatable && rhs.v.arr.len != v->val.v.arr.len)) {
                        int dims[7];
                        for (int i = 0; i < rhs.v.arr.n_dims; i++) dims[i] = rhs.v.arr.dims[i];
                        free_value(&v->val);
                        v->val = make_array(rhs.v.arr.elem_type, dims, rhs.v.arr.n_dims);
                    }
                    if (rhs.v.arr.len != v->val.v.arr.len)
                        ofort_error(I, "Array assignment shape mismatch");
                    for (int i = 0; i < v->val.v.arr.len; i++) {
                        OfortValue elem = copy_value(rhs.v.arr.data[i]);
                        if (v->val.v.arr.elem_type == FVAL_CHARACTER)
                            elem = resize_character_value(elem, v->char_len);
                        free_value(&v->val.v.arr.data[i]);
                        v->val.v.arr.data[i] = elem;
                    }
                } else {
                    for (int i = 0; i < v->val.v.arr.len; i++) {
                        OfortValue elem = copy_value(rhs);
                        if (v->val.v.arr.elem_type == FVAL_CHARACTER)
                            elem = resize_character_value(elem, v->char_len);
                        free_value(&v->val.v.arr.data[i]);
                        v->val.v.arr.data[i] = elem;
                    }
                }
                free_value(&rhs);
            } else {
                set_var(I, lhs->name, rhs);
            }
        } else if (lhs->type == FND_FUNC_CALL) {
            /* Array element assignment: arr(i) = val */
            OfortVar *var = find_var(I, lhs->name);
            if (!var) ofort_error(I, "Undefined variable '%s'", lhs->name);
            if (var->is_protected) ofort_error(I, "Cannot assign to PROTECTED variable '%s'", lhs->name);
            if (var->val.type != FVAL_ARRAY)
                ofort_error(I, "'%s' is not an array", lhs->name);

            assign_array_ref(I, var, lhs, &rhs);
            free_value(&rhs);
        } else if (lhs->type == FND_MEMBER) {
            /* Derived type member assignment: obj%field = val */
            if ((str_eq_nocase(lhs->name, "re") || str_eq_nocase(lhs->name, "im")) &&
                lhs->children[0]->type == FND_IDENT) {
                int want_re = str_eq_nocase(lhs->name, "re");
                OfortVar *v = find_var(I, lhs->children[0]->name);
                if (!v) ofort_error(I, "Undefined variable '%s'", lhs->children[0]->name);
                if (v->val.type == FVAL_COMPLEX) {
                    if (want_re) v->val.v.cx.re = val_to_real(rhs);
                    else v->val.v.cx.im = val_to_real(rhs);
                    free_value(&rhs);
                    break;
                }
                if (v->val.type == FVAL_ARRAY && v->val.v.arr.elem_type == FVAL_COMPLEX) {
                    if (rhs.type == FVAL_ARRAY && rhs.v.arr.len != v->val.v.arr.len)
                        ofort_error(I, "Array size mismatch in complex part assignment");
                    for (int i = 0; i < v->val.v.arr.len; i++) {
                        double part = rhs.type == FVAL_ARRAY ? val_to_real(rhs.v.arr.data[i]) : val_to_real(rhs);
                        if (v->val.v.arr.data[i].type != FVAL_COMPLEX) {
                            free_value(&v->val.v.arr.data[i]);
                            v->val.v.arr.data[i] = make_complex(0.0, 0.0);
                        }
                        if (want_re) v->val.v.arr.data[i].v.cx.re = part;
                        else v->val.v.arr.data[i].v.cx.im = part;
                    }
                    free_value(&rhs);
                    break;
                }
            }
            OfortValue obj = eval_node(I, lhs->children[0]);
            if (obj.type != FVAL_DERIVED) ofort_error(I, "Cannot access member of non-derived type");
            /* Find the variable to modify in place */
            if (lhs->children[0]->type == FND_IDENT) {
                OfortVar *v = find_var(I, lhs->children[0]->name);
                if (!v) ofort_error(I, "Undefined variable");
                char upper[256];
                str_upper(upper, lhs->name, 256);
                for (int i = 0; i < v->val.v.dt.n_fields; i++) {
                    char fu[256];
                    str_upper(fu, v->val.v.dt.field_names[i], 256);
                    if (strcmp(upper, fu) == 0) {
                        free_value(&v->val.v.dt.fields[i]);
                        v->val.v.dt.fields[i] = rhs;
                        free_value(&obj);
                        return;
                    }
                }
            }
            free_value(&obj);
            free_value(&rhs);
            ofort_error(I, "Unknown member '%s'", lhs->name);
        } else {
            free_value(&rhs);
            ofort_error(I, "Invalid assignment target");
        }
        break;
    }

    case FND_IF: {
        OfortValue cond = eval_node(I, n->children[0]);
        int is_true = val_to_logical(cond);
        free_value(&cond);
        if (is_true) {
            exec_node(I, n->children[1]);
        } else if (n->n_children > 2 && n->children[2]) {
            exec_node(I, n->children[2]);
        }
        break;
    }

    case FND_DO_LOOP: {
        OfortValue start = eval_node(I, n->children[0]);
        OfortValue end = eval_node(I, n->children[1]);
        OfortValue step = eval_node(I, n->children[2]);
        long long s = val_to_int(start), e = val_to_int(end), st = val_to_int(step);
        free_value(&start); free_value(&end); free_value(&step);

        if (st == 0) ofort_error(I, "DO loop step cannot be zero");

        set_var(I, n->name, make_integer(s));
        OfortVar *loop_var = I->fast_mode ? find_var(I, n->name) : NULL;
        long long iter = s;
        for (;;) {
            if (st > 0 && iter > e) break;
            if (st < 0 && iter < e) break;
            if (loop_var && loop_var->val.type == FVAL_INTEGER && !loop_var->is_parameter && !loop_var->is_protected) {
                loop_var->val.v.i = iter;
            } else {
                set_var(I, n->name, make_integer(iter));
            }
            exec_node(I, n->children[3]);
            if (I->returning || I->stopping) break;
            if (I->exiting) { I->exiting = 0; break; }
            if (I->cycling) { I->cycling = 0; }
            iter += st;
        }
        if (!I->returning && !I->stopping) {
            if (loop_var && loop_var->val.type == FVAL_INTEGER && !loop_var->is_parameter && !loop_var->is_protected) {
                loop_var->val.v.i = iter;
            } else {
                set_var(I, n->name, make_integer(iter));
            }
        }
        break;
    }

    case FND_DO_WHILE: {
        int max_iter = 1000000;
        while (max_iter-- > 0) {
            OfortValue cond = eval_node(I, n->children[0]);
            int is_true = val_to_logical(cond);
            free_value(&cond);
            if (!is_true) break;
            exec_node(I, n->children[1]);
            if (I->returning || I->stopping) break;
            if (I->exiting) { I->exiting = 0; break; }
            if (I->cycling) { I->cycling = 0; }
        }
        if (max_iter < 0 && !I->returning && !I->stopping)
            ofort_error(I, "DO WHILE exceeded iteration safety limit");
        break;
    }

    case FND_DO_FOREVER: {
        int max_iter = 1000000;
        while (max_iter-- > 0) {
            exec_node(I, n->children[0]);
            if (I->returning || I->stopping) break;
            if (I->exiting) { I->exiting = 0; break; }
            if (I->cycling) { I->cycling = 0; }
        }
        if (max_iter < 0 && !I->returning && !I->stopping)
            ofort_error(I, "DO exceeded iteration safety limit");
        break;
    }

    case FND_SELECT_CASE: {
        OfortValue sel = eval_node(I, n->children[0]);
        int matched = 0;
        for (int i = 0; i < n->n_stmts && !matched; i++) {
            OfortNode *cb = n->stmts[i];
            if (!cb->children[0]) {
                /* DEFAULT */
                int body_idx = cb->n_children - 1;
                exec_node(I, cb->children[body_idx]);
                matched = 1;
            } else {
                OfortValue case_val = eval_node(I, cb->children[0]);
                int match = 0;
                if (cb->n_children >= 3) {
                    /* range: lo:hi */
                    OfortValue hi = eval_node(I, cb->children[1]);
                    long long sv = val_to_int(sel);
                    match = (sv >= val_to_int(case_val) && sv <= val_to_int(hi));
                    free_value(&hi);
                } else {
                    /* single value */
                    if (sel.type == FVAL_CHARACTER || case_val.type == FVAL_CHARACTER) {
                        char sb[OFORT_MAX_STRLEN], cb2[OFORT_MAX_STRLEN];
                        value_to_string(I, sel, sb, sizeof(sb));
                        value_to_string(I, case_val, cb2, sizeof(cb2));
                        match = (strcmp(sb, cb2) == 0);
                    } else {
                        match = (val_to_int(sel) == val_to_int(case_val));
                    }
                }
                free_value(&case_val);
                if (match) {
                    int body_idx = cb->n_children - 1;
                    exec_node(I, cb->children[body_idx]);
                    matched = 1;
                }
            }
        }
        free_value(&sel);
        break;
    }

    case FND_PRINT: {
        int nvals = 0;
        OfortValue *vals = eval_io_list(I, n, &nvals);
        format_output(I, n->format_str, vals, nvals);
        for (int i = 0; i < nvals; i++) free_value(&vals[i]);
        free(vals);
        break;
    }

    case FND_WRITE: {
        int nvals = 0;
        OfortValue *vals = eval_io_list(I, n, &nvals);
        if (n->children[0]) {
            OfortValue uv = eval_node(I, n->children[0]);
            int unit = (int)val_to_int(uv);
            OfortUnitFile *entry = find_unit_file(I, unit);
            free_value(&uv);
            if (!entry && unit == 6) {
                format_output(I, n->format_str, vals, nvals);
            } else {
                if (!entry) ofort_error(I, "Unit %d is not open", unit);
                if (n->bool_val) write_values_to_stream_file(I, entry->path, vals, nvals);
                else write_values_to_file(I, entry->path, vals, nvals);
            }
        } else {
            format_output(I, n->format_str, vals, nvals);
        }
        for (int i = 0; i < nvals; i++) free_value(&vals[i]);
        free(vals);
        break;
    }

    case FND_READ_STMT:
        if (n->children[0]) {
            OfortValue uv = eval_node(I, n->children[0]);
            if (uv.type == FVAL_CHARACTER) {
                read_values_from_string(I, uv.v.s ? uv.v.s : "", n);
                free_value(&uv);
            } else {
                int unit = (int)val_to_int(uv);
                OfortUnitFile *entry = find_unit_file(I, unit);
                free_value(&uv);
                if (!entry) ofort_error(I, "Unit %d is not open", unit);
                if (n->bool_val) read_values_from_stream_file(I, entry, n);
                else read_values_from_file(I, entry->path, n);
            }
            break;
        }
        /* READ without an external unit is a no-op in this interpreter. */
        for (int i = 0; i < n->n_stmts; i++) {
            if (n->stmts[i]->type == FND_IDENT) {
                OfortVar *v = find_var(I, n->stmts[i]->name);
                if (!v) {
                    declare_var(I, n->stmts[i]->name, make_integer(0));
                }
            }
        }
        break;

    case FND_OPEN: {
        if (!n->children[0] || !n->children[1])
            ofort_error(I, "OPEN requires UNIT and FILE");
        OfortValue uv = eval_node(I, n->children[0]);
        OfortValue fv = eval_node(I, n->children[1]);
        int unit = (int)val_to_int(uv);
        if (fv.type != FVAL_CHARACTER)
            ofort_error(I, "OPEN FILE must be CHARACTER");
        set_unit_file(I, unit, fv.v.s ? fv.v.s : "");
        free_value(&uv);
        free_value(&fv);
        break;
    }

    case FND_CLOSE: {
        if (n->children[0]) {
            OfortValue uv = eval_node(I, n->children[0]);
            remove_unit_file(I, (int)val_to_int(uv));
            free_value(&uv);
        }
        break;
    }

    case FND_CALL: {
        char call_upper[256];
        str_upper(call_upper, n->name, 256);
        if (strcmp(call_upper, "RANDOM_SEED") == 0) {
            for (int i = 0; i < n->n_stmts; i++) {
                if (n->param_names[i][0] && str_eq_nocase(n->param_names[i], "size") &&
                    n->stmts[i]->type == FND_IDENT) {
                    set_var(I, n->stmts[i]->name, make_integer(1));
                }
            }
            break;
        }
        if (strcmp(call_upper, "SYSTEM_CLOCK") == 0) {
            long long now = (long long)time(NULL);
            for (int i = 0; i < n->n_stmts; i++) {
                if (n->stmts[i]->type != FND_IDENT) continue;
                if (n->param_names[i][0] == '\0' && i == 0) {
                    set_var(I, n->stmts[i]->name, make_integer(now));
                } else if (str_eq_nocase(n->param_names[i], "count")) {
                    set_var(I, n->stmts[i]->name, make_integer(now));
                } else if (str_eq_nocase(n->param_names[i], "count_rate")) {
                    set_var(I, n->stmts[i]->name, make_integer(1));
                } else if (str_eq_nocase(n->param_names[i], "count_max")) {
                    set_var(I, n->stmts[i]->name, make_integer(LLONG_MAX));
                }
            }
            break;
        }
        if (strcmp(call_upper, "CPU_TIME") == 0) {
            OfortVar *time_var;
            OfortValType time_type;
            double seconds;
            if (n->n_stmts != 1 || n->stmts[0]->type != FND_IDENT)
                ofort_error(I, "CPU_TIME requires a variable argument");
            time_var = find_var(I, n->stmts[0]->name);
            if (!time_var)
                ofort_error(I, "Undefined variable '%s' in CPU_TIME", n->stmts[0]->name);
            if (time_var->val.type != FVAL_REAL && time_var->val.type != FVAL_DOUBLE)
                ofort_error(I, "CPU_TIME argument must be REAL");
            time_type = time_var->val.type;
            seconds = (double)clock() / (double)CLOCKS_PER_SEC;
            free_value(&time_var->val);
            time_var->val = time_type == FVAL_DOUBLE ? make_double(seconds) : make_real(seconds);
            break;
        }
        if (strcmp(call_upper, "DATE_AND_TIME") == 0) {
            time_t now = time(NULL);
            struct tm local_tm;
            struct tm utc_tm;
            time_t local_epoch;
            time_t utc_as_local_epoch;
            int offset_minutes;
            int millisecond = 0;
            char date_buf[32];
            char time_buf[16];
            char zone_buf[16];

            local_tm = *localtime(&now);
            utc_tm = *gmtime(&now);
            local_epoch = mktime(&local_tm);
            utc_as_local_epoch = mktime(&utc_tm);
            offset_minutes = (int)(difftime(local_epoch, utc_as_local_epoch) / 60.0);

            snprintf(date_buf, sizeof(date_buf), "%04d%02d%02d",
                     local_tm.tm_year + 1900, local_tm.tm_mon + 1, local_tm.tm_mday);
            snprintf(time_buf, sizeof(time_buf), "%02d%02d%02d.%03d",
                     local_tm.tm_hour, local_tm.tm_min, local_tm.tm_sec, millisecond);
            snprintf(zone_buf, sizeof(zone_buf), "%c%02d%02d",
                     offset_minutes < 0 ? '-' : '+',
                     abs(offset_minutes) / 60, abs(offset_minutes) % 60);

            for (int i = 0; i < n->n_stmts; i++) {
                OfortNode *arg = n->stmts[i];
                const char *name = n->param_names[i];
                if (arg->type != FND_IDENT) continue;
                if (str_eq_nocase(name, "date") || (name[0] == '\0' && i == 0)) {
                    set_var(I, arg->name, make_character(date_buf));
                } else if (str_eq_nocase(name, "time") || (name[0] == '\0' && i == 1)) {
                    set_var(I, arg->name, make_character(time_buf));
                } else if (str_eq_nocase(name, "zone") || (name[0] == '\0' && i == 2)) {
                    set_var(I, arg->name, make_character(zone_buf));
                } else if (str_eq_nocase(name, "values") || (name[0] == '\0' && i == 3)) {
                    OfortVar *values_var = find_var(I, arg->name);
                    int values[8];
                    if (!values_var)
                        ofort_error(I, "Undefined variable '%s' in DATE_AND_TIME", arg->name);
                    if (values_var->val.type != FVAL_ARRAY || values_var->val.v.arr.elem_type != FVAL_INTEGER ||
                        values_var->val.v.arr.len < 8)
                        ofort_error(I, "DATE_AND_TIME VALUES must be an integer array of size at least 8");
                    values[0] = local_tm.tm_year + 1900;
                    values[1] = local_tm.tm_mon + 1;
                    values[2] = local_tm.tm_mday;
                    values[3] = offset_minutes;
                    values[4] = local_tm.tm_hour;
                    values[5] = local_tm.tm_min;
                    values[6] = local_tm.tm_sec;
                    values[7] = millisecond;
                    for (int j = 0; j < 8; j++) {
                        free_value(&values_var->val.v.arr.data[j]);
                        values_var->val.v.arr.data[j] = make_integer(values[j]);
                    }
                }
            }
            break;
        }
        if (strcmp(call_upper, "RANDOM_NUMBER") == 0) {
            if (n->n_stmts != 1 || n->stmts[0]->type != FND_IDENT)
                ofort_error(I, "RANDOM_NUMBER requires a variable argument");

            OfortVar *harvest = find_var(I, n->stmts[0]->name);
            if (!harvest)
                ofort_error(I, "Undefined variable '%s' in RANDOM_NUMBER", n->stmts[0]->name);

            if (harvest->val.type == FVAL_ARRAY) {
                OfortValue *arr = &harvest->val;
                if (arr->v.arr.elem_type != FVAL_REAL && arr->v.arr.elem_type != FVAL_DOUBLE)
                    ofort_error(I, "RANDOM_NUMBER harvest array must be REAL");
                if (I->fast_mode) {
                    for (int i = 0; i < arr->v.arr.len; i++) {
                        arr->v.arr.data[i].v.r = random_unit();
                    }
                } else {
                    for (int i = 0; i < arr->v.arr.len; i++) {
                        free_value(&arr->v.arr.data[i]);
                        if (arr->v.arr.elem_type == FVAL_DOUBLE)
                            arr->v.arr.data[i] = make_double(random_unit());
                        else
                            arr->v.arr.data[i] = make_real(random_unit());
                    }
                }
            } else if (harvest->val.type == FVAL_REAL || harvest->val.type == FVAL_DOUBLE) {
                OfortValType t = harvest->val.type;
                if (I->fast_mode) {
                    harvest->val.v.r = random_unit();
                } else {
                    free_value(&harvest->val);
                    harvest->val = (t == FVAL_DOUBLE) ? make_double(random_unit()) : make_real(random_unit());
                }
            } else {
                ofort_error(I, "RANDOM_NUMBER harvest must be REAL");
            }
            break;
        }
        if (strcmp(call_upper, "GET_COMMAND_ARGUMENT") == 0) {
            int number = 0;
            const char *arg = "";
            int arg_len = 0;
            int status = 0;
            int value_idx = -1;
            int length_idx = -1;
            int status_idx = -1;

            if (n->n_stmts < 1)
                ofort_error(I, "GET_COMMAND_ARGUMENT requires NUMBER");

            for (int i = 0; i < n->n_stmts; i++) {
                if (str_eq_nocase(n->param_names[i], "value")) {
                    value_idx = i;
                } else if (str_eq_nocase(n->param_names[i], "length")) {
                    length_idx = i;
                } else if (str_eq_nocase(n->param_names[i], "status")) {
                    status_idx = i;
                } else if (i == 1 && n->param_names[i][0] == '\0') {
                    value_idx = i;
                } else if (i == 2 && n->param_names[i][0] == '\0') {
                    length_idx = i;
                } else if (i == 3 && n->param_names[i][0] == '\0') {
                    status_idx = i;
                }
            }

            {
                OfortValue number_val = eval_node(I, n->stmts[0]);
                number = (int)val_to_int(number_val);
                free_value(&number_val);
            }

            if (number == 0) {
                arg = "ofort";
            } else if (number > 0 && number <= I->command_argc) {
                arg = I->command_args[number - 1];
            } else {
                status = 1;
            }
            arg_len = status == 0 ? (int)strlen(arg) : 0;

            if (value_idx >= 0) {
                if (n->stmts[value_idx]->type != FND_IDENT)
                    ofort_error(I, "GET_COMMAND_ARGUMENT VALUE must be a variable");
                OfortVar *value_var = find_var(I, n->stmts[value_idx]->name);
                if (!value_var)
                    ofort_error(I, "Undefined variable '%s' in GET_COMMAND_ARGUMENT", n->stmts[value_idx]->name);
                if (value_var->val.type != FVAL_CHARACTER)
                    ofort_error(I, "GET_COMMAND_ARGUMENT VALUE must be CHARACTER");
                if (status == 0 && value_var->char_len > 0 && arg_len > value_var->char_len) {
                    status = -1;
                }
                set_var(I, n->stmts[value_idx]->name, make_character(status > 0 ? "" : arg));
            }
            if (length_idx >= 0) {
                if (n->stmts[length_idx]->type != FND_IDENT)
                    ofort_error(I, "GET_COMMAND_ARGUMENT LENGTH must be a variable");
                set_var(I, n->stmts[length_idx]->name, make_integer(arg_len));
            }
            if (status_idx >= 0) {
                if (n->stmts[status_idx]->type != FND_IDENT)
                    ofort_error(I, "GET_COMMAND_ARGUMENT STATUS must be a variable");
                set_var(I, n->stmts[status_idx]->name, make_integer(status));
            }
            break;
        }
        if (strcmp(call_upper, "MVBITS") == 0) {
            OfortValue from_val, frompos_val, len_val, topos_val;
            OfortVar *to_var;
            int kind, bits;
            long long frompos, len, topos;
            unsigned long long source, dest, field, mask;
            if (n->n_stmts < 5)
                ofort_error(I, "MVBITS requires 5 arguments");
            if (n->stmts[3]->type != FND_IDENT)
                ofort_error(I, "MVBITS TO argument must be a variable");
            to_var = find_var(I, n->stmts[3]->name);
            if (!to_var)
                ofort_error(I, "Undefined variable '%s' in MVBITS", n->stmts[3]->name);
            if (to_var->val.type != FVAL_INTEGER)
                ofort_error(I, "MVBITS TO argument must be integer");

            from_val = eval_node(I, n->stmts[0]);
            frompos_val = eval_node(I, n->stmts[1]);
            len_val = eval_node(I, n->stmts[2]);
            topos_val = eval_node(I, n->stmts[4]);
            if (from_val.type != FVAL_INTEGER || frompos_val.type != FVAL_INTEGER ||
                len_val.type != FVAL_INTEGER || topos_val.type != FVAL_INTEGER)
                ofort_error(I, "MVBITS requires integer arguments");

            kind = to_var->val.kind ? to_var->val.kind : 4;
            bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
            frompos = frompos_val.v.i;
            len = len_val.v.i;
            topos = topos_val.v.i;
            if (frompos < 0 || len < 0 || topos < 0 ||
                frompos > bits || topos > bits || len > bits ||
                frompos + len > bits || topos + len > bits)
                ofort_error(I, "MVBITS bit range out of range");

            if (len > 0) {
                source = (unsigned long long)from_val.v.i;
                dest = (unsigned long long)to_var->val.v.i;
                mask = len == 64 ? ~0ULL : ((1ULL << (unsigned int)len) - 1ULL);
                field = (source >> (unsigned int)frompos) & mask;
                dest &= ~(mask << (unsigned int)topos);
                dest |= field << (unsigned int)topos;
                free_value(&to_var->val);
                to_var->val = make_integer_kind((long long)dest, kind);
            }
            free_value(&from_val);
            free_value(&frompos_val);
            free_value(&len_val);
            free_value(&topos_val);
            break;
        }

        /* Evaluate arguments */
        int nargs = n->n_stmts;
        OfortValue args[OFORT_MAX_PARAMS];
        for (int i = 0; i < nargs; i++) args[i] = eval_node(I, n->stmts[i]);

        /* Check for intrinsic subroutines */
        /* (none currently — user subroutines only) */

        OfortFunc *func = find_func(I, n->name);
        if (!func) {
            for (int i = 0; i < nargs; i++) free_value(&args[i]);
            ofort_error(I, "Unknown subroutine '%s' at line %d", n->name, n->line);
        }

        OfortNode *fn = func->node;
        push_scope(I);
        /* Bind parameters */
        for (int i = 0; i < fn->n_params; i++) {
            OfortVar *pv;
            if (i < nargs && args[i].type != FVAL_VOID) {
                pv = declare_var(I, fn->param_names[i], copy_value(args[i]));
            } else if (fn->param_optional[i]) {
                pv = declare_absent_optional_var(I, fn->param_names[i]);
            } else {
                ofort_error(I, "Missing required argument '%s' in call to '%s'",
                            fn->param_names[i], fn->name);
            }
            pv->intent = fn->param_intents[i];
        }
        restore_saved_vars(I, func);

        I->procedure_depth++;
        exec_node(I, fn->children[0]);
        I->procedure_depth--;
        I->returning = 0;

        /* Handle INTENT(OUT/INOUT) — copy back */
        for (int i = 0; i < fn->n_params && i < nargs; i++) {
            if (fn->param_intents[i] != 1) {
                OfortVar *pv = find_var(I, fn->param_names[i]);
                if (pv && pv->present && n->stmts[i]->type == FND_IDENT) {
                    free_value(&args[i]);
                    args[i] = copy_value(pv->val);
                }
            }
        }

        store_saved_vars(func, I->current_scope);
        pop_scope(I);
        for (int i = 0; i < fn->n_params && i < nargs; i++) {
            if (n->stmts[i]->type == FND_IDENT && fn->param_intents[i] != 1 &&
                args[i].type != FVAL_VOID) {
                set_var(I, n->stmts[i]->name, copy_value(args[i]));
            }
        }
        for (int i = 0; i < nargs; i++) free_value(&args[i]);
        break;
    }

    case FND_SUBROUTINE:
    case FND_FUNCTION: {
        /* Register function/subroutine for later call */
        /* Also scan body for INTENT declarations */
        OfortNode *body = n->children[0];
        if (body) {
            for (int i = 0; i < body->n_stmts; i++) {
                OfortNode *s = body->stmts[i];
                if (s->type == FND_BLOCK) {
                    /* declaration block */
                    for (int j = 0; j < s->n_stmts; j++) {
                        OfortNode *d = s->stmts[j];
                        if (d->type == FND_VARDECL && (d->intent != 0 || d->is_optional)) {
                            /* Match parameter name */
                            char du[256];
                            str_upper(du, d->name, 256);
                            for (int k = 0; k < n->n_params; k++) {
                                char pu[256];
                                str_upper(pu, n->param_names[k], 256);
                                if (strcmp(du, pu) == 0) {
                                    n->param_intents[k] = d->intent;
                                    n->param_types[k] = d->val_type;
                                    n->param_optional[k] = d->is_optional;
                                    break;
                                }
                            }
                        }
                    }
                } else if (s->type == FND_VARDECL && (s->intent != 0 || s->is_optional)) {
                    char du[256];
                    str_upper(du, s->name, 256);
                    for (int k = 0; k < n->n_params; k++) {
                        char pu[256];
                        str_upper(pu, n->param_names[k], 256);
                        if (strcmp(du, pu) == 0) {
                            n->param_intents[k] = s->intent;
                            n->param_types[k] = s->val_type;
                            n->param_optional[k] = s->is_optional;
                            break;
                        }
                    }
                }
            }
        }
        register_func(I, n->name, n, n->type == FND_FUNCTION);
        break;
    }

    case FND_ALLOCATE: {
        OfortVar *var = find_var(I, n->name);
        if (!var) ofort_error(I, "Variable '%s' not found for ALLOCATE", n->name);
        /* Get dimensions */
        int dims[7];
        int ndims = n->n_stmts;
        OfortValType elem_type = var->val.v.arr.elem_type ? var->val.v.arr.elem_type : FVAL_REAL;

        if (ndims > 0) {
            for (int i = 0; i < ndims; i++) {
                OfortValue dv = eval_node(I, n->stmts[i]);
                dims[i] = (int)val_to_int(dv);
                free_value(&dv);
            }
        } else if (n->children[1]) {
            OfortValue mold = eval_node(I, n->children[1]);
            if (mold.type != FVAL_ARRAY)
                ofort_error(I, "ALLOCATE MOLD must be an array");
            ndims = mold.v.arr.n_dims;
            elem_type = mold.v.arr.elem_type;
            for (int i = 0; i < ndims; i++) dims[i] = mold.v.arr.dims[i];
            free_value(&mold);
        } else if (n->children[0]) {
            OfortValue source = eval_node(I, n->children[0]);
            if (source.type == FVAL_ARRAY) {
                ndims = source.v.arr.n_dims;
                elem_type = source.v.arr.elem_type;
                for (int i = 0; i < ndims; i++) dims[i] = source.v.arr.dims[i];
            } else {
                ndims = 1;
                dims[0] = 1;
                elem_type = source.type;
            }
            free_value(&source);
        } else {
            ofort_error(I, "ALLOCATE requires dimensions, SOURCE, or MOLD");
        }
        free_value(&var->val);
        var->val = make_array(elem_type, dims, ndims);
        if (n->children[0]) {
            OfortValue source = eval_node(I, n->children[0]);
            if (source.type == FVAL_ARRAY) {
                int count = source.v.arr.len < var->val.v.arr.len ? source.v.arr.len : var->val.v.arr.len;
                for (int i = 0; i < count; i++) {
                    free_value(&var->val.v.arr.data[i]);
                    var->val.v.arr.data[i] = copy_value(source.v.arr.data[i]);
                }
            } else {
                for (int i = 0; i < var->val.v.arr.len; i++) {
                    free_value(&var->val.v.arr.data[i]);
                    var->val.v.arr.data[i] = copy_value(source);
                }
            }
            free_value(&source);
        }
        break;
    }

    case FND_DEALLOCATE: {
        OfortVar *var = find_var(I, n->name);
        if (!var) ofort_error(I, "Variable '%s' not found for DEALLOCATE", n->name);
        free_value(&var->val);
        var->val.type = FVAL_ARRAY;
        memset(&var->val.v.arr, 0, sizeof(var->val.v.arr));
        var->val.v.arr.allocated = 0;
        break;
    }

    case FND_RETURN:
        I->returning = 1;
        break;

    case FND_EXIT:
        I->exiting = 1;
        break;

    case FND_CYCLE:
        I->cycling = 1;
        break;

    case FND_STOP:
        I->stopping = 1;
        if (n->str_val[0]) {
            out_appendf(I, "STOP %s\n", n->str_val);
        }
        break;

    case FND_EXPR_STMT: {
        if (n->children[0] && n->children[0]->type == FND_FUNC_CALL &&
            str_eq_nocase(n->children[0]->name, "nullify")) {
            OfortNode *call = n->children[0];
            for (int i = 0; i < call->n_stmts; i++) {
                OfortVar *v;
                if (call->stmts[i]->type != FND_IDENT)
                    ofort_error(I, "NULLIFY requires pointer variable arguments");
                v = find_var(I, call->stmts[i]->name);
                if (!v || !v->is_pointer)
                    ofort_error(I, "NULLIFY argument is not a pointer");
                v->pointer_associated = 0;
                v->pointer_target[0] = '\0';
                v->pointer_has_slice = 0;
                v->pointer_slice_start = 0;
                v->pointer_slice_end = 0;
            }
            break;
        }
        OfortValue v = eval_node(I, n->children[0]);
        if (I->print_expr_statements && v.type != FVAL_VOID) {
            char buf[1024];
            value_to_string(I, v, buf, sizeof(buf));
            out_append_raw(I, buf);
            out_append_raw(I, "\n");
        }
        free_value(&v);
        break;
    }

    default:
        break;
    }
    if (profile_line > 0) {
        add_line_profile_time(I, profile_line, ofort_monotonic_seconds() - profile_start);
    }
}

/* ══════════════════════════════════════════════
 *  INTRINSIC FUNCTIONS
 * ══════════════════════════════════════════════ */

static const char *intrinsic_names[] = {
    /* Math */
    "ABS", "SQRT", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "ATAN2",
    "EXP", "LOG", "LOG10", "MOD", "MODULO", "DIM", "MAX", "MIN", "FLOOR", "CEILING", "AINT", "NINT",
    "REAL", "INT", "DBLE", "DPROD", "CMPLX", "AIMAG", "CONJG", "SIGN", "KIND", "TRANSFER",
    "BIT_SIZE", "BTEST", "IAND", "IEOR", "IOR", "IBCLR", "IBITS", "IBSET", "ISHFT", "ISHFTC", "MASKL", "MASKR",
    "DIGITS", "EPSILON", "FRACTION", "EXPONENT", "RADIX", "HUGE", "TINY", "NEAREST", "PRECISION", "RANGE", "RRSPACING", "SPACING", "SCALE",
    "SET_EXPONENT",
    "SELECTED_INT_KIND", "SELECTED_REAL_KIND",
    /* String */
    "LEN", "LEN_TRIM", "TRIM", "ADJUSTL", "ADJUSTR", "INDEX", "SCAN", "VERIFY",
    "CHAR", "ICHAR", "ACHAR", "IACHAR", "REPEAT",
    /* Array */
    "SIZE", "SHAPE", "PACK", "UNPACK", "MERGE", "SUM", "PRODUCT", "MAXVAL", "MINVAL", "MAXLOC", "MINLOC",
    "DOT_PRODUCT", "MATMUL", "TRANSPOSE", "RESHAPE", "SPREAD", "EOSHIFT", "CSHIFT",
    "COUNT", "ANY", "ALL", "ALLOCATED", "LBOUND", "UBOUND",
    /* Type conversion */
    "FLOAT", "DFLOAT", "SNGL", "LOGICAL",
    /* Command line */
    "COMMAND_ARGUMENT_COUNT",
    NULL
};

static int is_intrinsic(const char *name) {
    char upper[256];
    str_upper(upper, name, 256);
    for (int i = 0; intrinsic_names[i]; i++) {
        if (strcmp(upper, intrinsic_names[i]) == 0) return 1;
    }
    return 0;
}

static int is_elemental_unary_intrinsic(const char *upper) {
    return strcmp(upper, "ABS") == 0 ||
           strcmp(upper, "SQRT") == 0 ||
           strcmp(upper, "SIN") == 0 ||
           strcmp(upper, "COS") == 0 ||
           strcmp(upper, "TAN") == 0 ||
           strcmp(upper, "ASIN") == 0 ||
           strcmp(upper, "ACOS") == 0 ||
           strcmp(upper, "ATAN") == 0 ||
           strcmp(upper, "EXP") == 0 ||
           strcmp(upper, "LOG") == 0 ||
           strcmp(upper, "LOG10") == 0 ||
           strcmp(upper, "FLOOR") == 0 ||
           strcmp(upper, "CEILING") == 0 ||
           strcmp(upper, "AINT") == 0 ||
           strcmp(upper, "NINT") == 0 ||
           strcmp(upper, "REAL") == 0 ||
           strcmp(upper, "FLOAT") == 0 ||
           strcmp(upper, "SNGL") == 0 ||
           strcmp(upper, "INT") == 0 ||
           strcmp(upper, "DBLE") == 0 ||
           strcmp(upper, "DFLOAT") == 0 ||
           strcmp(upper, "AIMAG") == 0 ||
           strcmp(upper, "CONJG") == 0 ||
           strcmp(upper, "LOGICAL") == 0;
}

static int intrinsic_arg_index(char arg_names[OFORT_MAX_PARAMS][256], int nargs, const char *name) {
    if (!arg_names || !name) return -1;
    for (int i = 0; i < nargs; i++) {
        if (arg_names[i][0] && str_eq_nocase(arg_names[i], name)) {
            return i;
        }
    }
    return -1;
}

static OfortValType elemental_result_type(const char *upper, OfortValType input_type) {
    if (strcmp(upper, "ABS") == 0 && input_type == FVAL_INTEGER) return FVAL_INTEGER;
    if (strcmp(upper, "FLOOR") == 0 ||
        strcmp(upper, "CEILING") == 0 ||
        strcmp(upper, "NINT") == 0 ||
        strcmp(upper, "INT") == 0) return FVAL_INTEGER;
    if (strcmp(upper, "DBLE") == 0 || strcmp(upper, "DFLOAT") == 0) return FVAL_DOUBLE;
    if (strcmp(upper, "CONJG") == 0) return FVAL_COMPLEX;
    if (strcmp(upper, "LOGICAL") == 0) return FVAL_LOGICAL;
    return FVAL_REAL;
}

static int integer_kind_bits(int kind) {
    if (kind == 1) return 8;
    if (kind == 2) return 16;
    if (kind == 8) return 64;
    return 32;
}

static long long signed_mask_value(unsigned long long value, int bits) {
    unsigned long long mask;
    unsigned long long sign_bit;
    if (bits >= 64) return (long long)value;
    mask = (1ULL << (unsigned int)bits) - 1ULL;
    value &= mask;
    sign_bit = 1ULL << (unsigned int)(bits - 1);
    if (value & sign_bit) value |= ~mask;
    return (long long)value;
}

static int transfer_type_size(OfortValType type, int char_len) {
    switch (type) {
    case FVAL_INTEGER:
    case FVAL_REAL:
    case FVAL_LOGICAL:
        return 4;
    case FVAL_DOUBLE:
        return 8;
    case FVAL_COMPLEX:
        return 8;
    case FVAL_CHARACTER:
        return char_len > 0 ? char_len : 1;
    default:
        return 0;
    }
}

static int transfer_mold_char_len(OfortValue mold) {
    if (mold.type == FVAL_CHARACTER)
        return mold.v.s ? (int)strlen(mold.v.s) : 1;
    if (mold.type == FVAL_ARRAY && mold.v.arr.elem_type == FVAL_CHARACTER && mold.v.arr.len > 0)
        return mold.v.arr.data[0].v.s ? (int)strlen(mold.v.arr.data[0].v.s) : 1;
    return 1;
}

static int transfer_append_bytes_from_value(OfortValue value, unsigned char *bytes, int max_bytes) {
    int used = 0;
    if (max_bytes <= 0) return 0;
    if (value.type == FVAL_ARRAY) {
        for (int i = 0; i < value.v.arr.len && used < max_bytes; i++) {
            used += transfer_append_bytes_from_value(value.v.arr.data[i], bytes + used, max_bytes - used);
        }
        return used;
    }
    if (value.type == FVAL_INTEGER) {
        uint32_t u = (uint32_t)value.v.i;
        int n = max_bytes < 4 ? max_bytes : 4;
        memcpy(bytes, &u, (size_t)n);
        return n;
    }
    if (value.type == FVAL_REAL) {
        float f = (float)value.v.r;
        int n = max_bytes < 4 ? max_bytes : 4;
        memcpy(bytes, &f, (size_t)n);
        return n;
    }
    if (value.type == FVAL_DOUBLE) {
        double d = value.v.r;
        int n = max_bytes < 8 ? max_bytes : 8;
        memcpy(bytes, &d, (size_t)n);
        return n;
    }
    if (value.type == FVAL_LOGICAL) {
        uint32_t u = value.v.b ? 1U : 0U;
        int n = max_bytes < 4 ? max_bytes : 4;
        memcpy(bytes, &u, (size_t)n);
        return n;
    }
    if (value.type == FVAL_COMPLEX) {
        float parts[2];
        int n = max_bytes < 8 ? max_bytes : 8;
        parts[0] = (float)value.v.cx.re;
        parts[1] = (float)value.v.cx.im;
        memcpy(bytes, parts, (size_t)n);
        return n;
    }
    if (value.type == FVAL_CHARACTER) {
        int n = value.v.s ? (int)strlen(value.v.s) : 0;
        if (n > max_bytes) n = max_bytes;
        if (n > 0) memcpy(bytes, value.v.s, (size_t)n);
        return n;
    }
    return 0;
}

static OfortValue transfer_value_from_bytes(OfortValType type, int kind, int char_len,
                                           const unsigned char *bytes, int nbytes, int offset) {
    unsigned char tmp[16];
    int size = transfer_type_size(type, char_len);
    memset(tmp, 0, sizeof(tmp));
    if (size > (int)sizeof(tmp)) size = (int)sizeof(tmp);
    for (int i = 0; i < size; i++) {
        int src = offset + i;
        if (src >= 0 && src < nbytes) tmp[i] = bytes[src];
    }
    switch (type) {
    case FVAL_INTEGER: {
        uint32_t u = 0;
        memcpy(&u, tmp, sizeof(u));
        return make_integer_kind(signed_mask_value(u, 32), kind > 0 ? kind : 4);
    }
    case FVAL_REAL: {
        float f = 0.0f;
        memcpy(&f, tmp, sizeof(f));
        return make_real((double)f);
    }
    case FVAL_DOUBLE: {
        double d = 0.0;
        memcpy(&d, tmp, sizeof(d));
        return make_double(d);
    }
    case FVAL_LOGICAL: {
        uint32_t u = 0;
        memcpy(&u, tmp, sizeof(u));
        return make_logical(u != 0);
    }
    case FVAL_CHARACTER: {
        char buf[OFORT_MAX_STRLEN];
        if (char_len <= 0) char_len = 1;
        if (char_len >= OFORT_MAX_STRLEN) char_len = OFORT_MAX_STRLEN - 1;
        memset(buf, 0, sizeof(buf));
        memcpy(buf, tmp, (size_t)char_len);
        return make_character(buf);
    }
    default:
        return make_void_val();
    }
}

static OfortValue call_intrinsic(OfortInterpreter *I, const char *name, OfortValue *args, int nargs,
                                char arg_names[OFORT_MAX_PARAMS][256]) {
    char upper[256];
    str_upper(upper, name, 256);

    if (nargs > 0 && args[0].type == FVAL_ARRAY && is_elemental_unary_intrinsic(upper)) {
        OfortValue result = copy_value(args[0]);
        result.v.arr.elem_type = elemental_result_type(upper, args[0].v.arr.elem_type);

        for (int i = 0; i < result.v.arr.len; i++) {
            OfortValue elem_arg = copy_value(args[0].v.arr.data[i]);
            OfortValue elem_result = call_intrinsic(I, name, &elem_arg, 1, NULL);
            free_value(&elem_arg);
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = elem_result;
        }

        return result;
    }

    if ((strcmp(upper, "MOD") == 0 || strcmp(upper, "MODULO") == 0 ||
         strcmp(upper, "DIM") == 0 || strcmp(upper, "SIGN") == 0) &&
        nargs >= 2 && (args[0].type == FVAL_ARRAY || args[1].type == FVAL_ARRAY)) {
        OfortValue *shape_arg = args[0].type == FVAL_ARRAY ? &args[0] : &args[1];
        OfortValType result_type = FVAL_REAL;
        OfortValue result;
        if ((strcmp(upper, "MOD") == 0 || strcmp(upper, "MODULO") == 0 || strcmp(upper, "DIM") == 0) &&
            ((args[0].type == FVAL_ARRAY ? args[0].v.arr.elem_type : args[0].type) == FVAL_INTEGER) &&
            ((args[1].type == FVAL_ARRAY ? args[1].v.arr.elem_type : args[1].type) == FVAL_INTEGER)) {
            result_type = FVAL_INTEGER;
        }
        if (strcmp(upper, "SIGN") == 0)
            result_type = args[0].type == FVAL_ARRAY ? args[0].v.arr.elem_type : args[0].type;
        result = make_array(result_type, shape_arg->v.arr.dims, shape_arg->v.arr.n_dims);
        if (args[0].type == FVAL_ARRAY && args[1].type == FVAL_ARRAY && args[0].v.arr.len != args[1].v.arr.len)
            ofort_error(I, "%s array arguments have different sizes", upper);
        for (int i = 0; i < result.v.arr.len; i++) {
            OfortValue elem_args[2];
            OfortValue elem_result;
            elem_args[0] = args[0].type == FVAL_ARRAY ? copy_value(args[0].v.arr.data[i]) : copy_value(args[0]);
            elem_args[1] = args[1].type == FVAL_ARRAY ? copy_value(args[1].v.arr.data[i]) : copy_value(args[1]);
            elem_result = call_intrinsic(I, name, elem_args, 2, NULL);
            free_value(&elem_args[0]);
            free_value(&elem_args[1]);
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = elem_result;
        }
        return result;
    }

    /* === Math intrinsics === */
    if (strcmp(upper, "TRANSFER") == 0) {
        int size_idx;
        int result_len = 0;
        int elem_size;
        int char_len;
        OfortValType result_type;
        int result_kind;
        unsigned char bytes[OFORT_MAX_STRLEN * 16];
        int nbytes;
        if (nargs < 2) ofort_error(I, "TRANSFER requires SOURCE and MOLD arguments");
        size_idx = intrinsic_arg_index(arg_names, nargs, "size");
        if (size_idx < 0 && nargs >= 3) size_idx = 2;
        result_type = args[1].type == FVAL_ARRAY ? args[1].v.arr.elem_type : args[1].type;
        result_kind = args[1].type == FVAL_ARRAY && args[1].v.arr.len > 0 ? args[1].v.arr.data[0].kind : args[1].kind;
        char_len = transfer_mold_char_len(args[1]);
        elem_size = transfer_type_size(result_type, char_len);
        if (elem_size <= 0) ofort_error(I, "TRANSFER mold type is not supported");
        memset(bytes, 0, sizeof(bytes));
        nbytes = transfer_append_bytes_from_value(args[0], bytes, (int)sizeof(bytes));
        if (size_idx >= 0) {
            int dims[1];
            OfortValue result;
            result_len = (int)val_to_int(args[size_idx]);
            if (result_len < 0) result_len = 0;
            dims[0] = result_len;
            result = make_array_with_char_len(result_type, dims, 1, char_len);
            for (int i = 0; i < result.v.arr.len; i++) {
                free_value(&result.v.arr.data[i]);
                result.v.arr.data[i] = transfer_value_from_bytes(result_type, result_kind, char_len, bytes, nbytes, i * elem_size);
            }
            return result;
        }
        if (args[1].type == FVAL_ARRAY) {
            OfortValue result = make_array_with_char_len(result_type, args[1].v.arr.dims, args[1].v.arr.n_dims, char_len);
            for (int i = 0; i < result.v.arr.len; i++) {
                free_value(&result.v.arr.data[i]);
                result.v.arr.data[i] = transfer_value_from_bytes(result_type, result_kind, char_len, bytes, nbytes, i * elem_size);
            }
            return result;
        }
        return transfer_value_from_bytes(result_type, result_kind, char_len, bytes, nbytes, 0);
    }

    if (strcmp(upper, "ABS") == 0) {
        if (nargs < 1) ofort_error(I, "ABS requires 1 argument");
        if (args[0].type == FVAL_INTEGER) return make_integer(args[0].v.i < 0 ? -args[0].v.i : args[0].v.i);
        if (args[0].type == FVAL_COMPLEX) return make_real(sqrt(args[0].v.cx.re * args[0].v.cx.re + args[0].v.cx.im * args[0].v.cx.im));
        return make_real(fabs(val_to_real(args[0])));
    }
    if (strcmp(upper, "SQRT") == 0) {
        if (nargs < 1) ofort_error(I, "SQRT requires 1 argument");
        return make_real(sqrt(val_to_real(args[0])));
    }
    if (strcmp(upper, "SIN") == 0) {
        if (nargs < 1) ofort_error(I, "SIN requires 1 argument");
        return make_real(sin(val_to_real(args[0])));
    }
    if (strcmp(upper, "COS") == 0) {
        if (nargs < 1) ofort_error(I, "COS requires 1 argument");
        return make_real(cos(val_to_real(args[0])));
    }
    if (strcmp(upper, "TAN") == 0) {
        return make_real(tan(val_to_real(args[0])));
    }
    if (strcmp(upper, "ASIN") == 0) {
        return make_real(asin(val_to_real(args[0])));
    }
    if (strcmp(upper, "ACOS") == 0) {
        return make_real(acos(val_to_real(args[0])));
    }
    if (strcmp(upper, "ATAN") == 0) {
        return make_real(atan(val_to_real(args[0])));
    }
    if (strcmp(upper, "ATAN2") == 0) {
        if (nargs < 2) ofort_error(I, "ATAN2 requires 2 arguments");
        return make_real(atan2(val_to_real(args[0]), val_to_real(args[1])));
    }
    if (strcmp(upper, "EXP") == 0) {
        return make_real(exp(val_to_real(args[0])));
    }
    if (strcmp(upper, "LOG") == 0) {
        return make_real(log(val_to_real(args[0])));
    }
    if (strcmp(upper, "LOG10") == 0) {
        return make_real(log10(val_to_real(args[0])));
    }
    if (strcmp(upper, "MOD") == 0) {
        if (nargs < 2) ofort_error(I, "MOD requires 2 arguments");
        if (args[0].type == FVAL_INTEGER && args[1].type == FVAL_INTEGER) {
            long long b = val_to_int(args[1]);
            if (b == 0) ofort_error(I, "MOD: division by zero");
            return make_integer(val_to_int(args[0]) % b);
        }
        return make_real(fmod(val_to_real(args[0]), val_to_real(args[1])));
    }
    if (strcmp(upper, "MODULO") == 0) {
        if (nargs < 2) ofort_error(I, "MODULO requires 2 arguments");
        if (args[0].type == FVAL_INTEGER && args[1].type == FVAL_INTEGER) {
            long long a = val_to_int(args[0]);
            long long p = val_to_int(args[1]);
            if (p == 0) ofort_error(I, "MODULO: division by zero");
            long long r = a % p;
            if (r != 0 && ((r < 0) != (p < 0))) r += p;
            return make_integer(r);
        }
        double p = val_to_real(args[1]);
        if (p == 0.0) ofort_error(I, "MODULO: division by zero");
        double r = fmod(val_to_real(args[0]), p);
        if (r != 0.0 && ((r < 0.0) != (p < 0.0))) r += p;
        return make_real(r);
    }
    if (strcmp(upper, "DIM") == 0) {
        if (nargs < 2) ofort_error(I, "DIM requires 2 arguments");
        if (args[0].type == FVAL_INTEGER && args[1].type == FVAL_INTEGER) {
            long long diff = val_to_int(args[0]) - val_to_int(args[1]);
            return make_integer(diff > 0 ? diff : 0);
        }
        double diff = val_to_real(args[0]) - val_to_real(args[1]);
        return make_real(diff > 0.0 ? diff : 0.0);
    }
    if (strcmp(upper, "MAX") == 0) {
        if (nargs < 2) ofort_error(I, "MAX requires at least 2 arguments");
        double result = val_to_real(args[0]);
        for (int i = 1; i < nargs; i++) {
            double v = val_to_real(args[i]);
            if (v > result) result = v;
        }
        if (args[0].type == FVAL_INTEGER) return make_integer((long long)result);
        return make_real(result);
    }
    if (strcmp(upper, "MIN") == 0) {
        if (nargs < 2) ofort_error(I, "MIN requires at least 2 arguments");
        double result = val_to_real(args[0]);
        for (int i = 1; i < nargs; i++) {
            double v = val_to_real(args[i]);
            if (v < result) result = v;
        }
        if (args[0].type == FVAL_INTEGER) return make_integer((long long)result);
        return make_real(result);
    }
    if (strcmp(upper, "FLOOR") == 0) {
        return make_integer((long long)floor(val_to_real(args[0])));
    }
    if (strcmp(upper, "CEILING") == 0) {
        return make_integer((long long)ceil(val_to_real(args[0])));
    }
    if (strcmp(upper, "AINT") == 0) {
        return make_real(trunc(val_to_real(args[0])));
    }
    if (strcmp(upper, "NINT") == 0) {
        return make_integer((long long)round(val_to_real(args[0])));
    }
    if (strcmp(upper, "SIGN") == 0) {
        if (nargs < 2) ofort_error(I, "SIGN requires 2 arguments");
        double a = fabs(val_to_real(args[0]));
        double b = val_to_real(args[1]);
        double result = b >= 0 ? a : -a;
        if (args[0].type == FVAL_INTEGER) return make_integer((long long)result);
        return make_real(result);
    }
    if (strcmp(upper, "KIND") == 0) {
        if (nargs < 1) ofort_error(I, "KIND requires 1 argument");
        switch (args[0].type) {
            case FVAL_CHARACTER: return make_integer(1);
            case FVAL_INTEGER: return make_integer(args[0].kind ? args[0].kind : 4);
            case FVAL_REAL: return make_integer(4);
            case FVAL_DOUBLE: return make_integer(8);
            case FVAL_COMPLEX: return make_integer(8);
            case FVAL_LOGICAL: return make_integer(4);
            default: return make_integer(0);
        }
    }
    if (strcmp(upper, "BIT_SIZE") == 0) {
        int kind;
        if (nargs < 1) ofort_error(I, "BIT_SIZE requires 1 argument");
        if (args[0].type != FVAL_INTEGER) ofort_error(I, "BIT_SIZE requires an integer argument");
        kind = args[0].kind ? args[0].kind : 4;
        return make_integer(integer_kind_bits(kind));
    }
    if (strcmp(upper, "BTEST") == 0) {
        int kind, bits;
        long long pos;
        unsigned long long value;
        if (nargs < 2) ofort_error(I, "BTEST requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "BTEST requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        pos = args[1].v.i;
        if (pos < 0 || pos >= bits) ofort_error(I, "BTEST bit position out of range");
        value = (unsigned long long)args[0].v.i;
        return make_logical(((value >> (unsigned int)pos) & 1ULL) != 0);
    }
    if (strcmp(upper, "IAND") == 0) {
        int kind;
        if (nargs < 2) ofort_error(I, "IAND requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "IAND requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        return make_integer_kind(args[0].v.i & args[1].v.i, kind);
    }
    if (strcmp(upper, "IEOR") == 0) {
        int kind;
        if (nargs < 2) ofort_error(I, "IEOR requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "IEOR requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        return make_integer_kind(args[0].v.i ^ args[1].v.i, kind);
    }
    if (strcmp(upper, "IOR") == 0) {
        int kind;
        if (nargs < 2) ofort_error(I, "IOR requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "IOR requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        return make_integer_kind(args[0].v.i | args[1].v.i, kind);
    }
    if (strcmp(upper, "IBCLR") == 0) {
        int kind, bits;
        long long pos;
        unsigned long long value;
        if (nargs < 2) ofort_error(I, "IBCLR requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "IBCLR requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        pos = args[1].v.i;
        if (pos < 0 || pos >= bits) ofort_error(I, "IBCLR bit position out of range");
        value = (unsigned long long)args[0].v.i;
        value &= ~(1ULL << (unsigned int)pos);
        return make_integer_kind((long long)value, kind);
    }
    if (strcmp(upper, "IBITS") == 0) {
        int kind, bits;
        long long pos, len;
        unsigned long long value, mask;
        if (nargs < 3) ofort_error(I, "IBITS requires 3 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER || args[2].type != FVAL_INTEGER)
            ofort_error(I, "IBITS requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        pos = args[1].v.i;
        len = args[2].v.i;
        if (pos < 0 || len < 0 || pos > bits || len > bits || pos + len > bits)
            ofort_error(I, "IBITS bit range out of range");
        if (len == 0) return make_integer_kind(0, kind);
        value = ((unsigned long long)args[0].v.i) >> (unsigned int)pos;
        mask = len == 64 ? ~0ULL : ((1ULL << (unsigned int)len) - 1ULL);
        return make_integer_kind((long long)(value & mask), kind);
    }
    if (strcmp(upper, "IBSET") == 0) {
        int kind, bits;
        long long pos;
        unsigned long long value;
        if (nargs < 2) ofort_error(I, "IBSET requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "IBSET requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        pos = args[1].v.i;
        if (pos < 0 || pos >= bits) ofort_error(I, "IBSET bit position out of range");
        value = (unsigned long long)args[0].v.i;
        value |= 1ULL << (unsigned int)pos;
        return make_integer_kind((long long)value, kind);
    }
    if (strcmp(upper, "ISHFT") == 0) {
        int kind, bits;
        long long shift;
        unsigned long long value;
        if (nargs < 2) ofort_error(I, "ISHFT requires 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "ISHFT requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        shift = args[1].v.i;
        if (shift <= -bits || shift >= bits) return make_integer_kind(0, kind);
        value = (unsigned long long)args[0].v.i;
        if (shift > 0) value <<= (unsigned int)shift;
        else if (shift < 0) value >>= (unsigned int)(-shift);
        return make_integer_kind((long long)value, kind);
    }
    if (strcmp(upper, "ISHFTC") == 0) {
        int kind, bits, size;
        long long shift;
        long long smod;
        unsigned int rshift;
        unsigned long long value, mask, field, rest, rotated;
        if (nargs < 2) ofort_error(I, "ISHFTC requires at least 2 arguments");
        if (args[0].type != FVAL_INTEGER || args[1].type != FVAL_INTEGER)
            ofort_error(I, "ISHFTC requires integer arguments");
        kind = args[0].kind ? args[0].kind : 4;
        bits = kind == 1 ? 8 : kind == 2 ? 16 : kind == 8 ? 64 : 32;
        size = bits;
        if (nargs >= 3) {
            if (args[2].type != FVAL_INTEGER) ofort_error(I, "ISHFTC SIZE must be integer");
            size = (int)args[2].v.i;
        }
        if (size <= 0 || size > bits) ofort_error(I, "ISHFTC size out of range");
        shift = args[1].v.i;
        smod = shift % size;
        if (smod < 0) smod += size;
        rshift = (unsigned int)smod;
        mask = size == 64 ? ~0ULL : ((1ULL << (unsigned int)size) - 1ULL);
        value = (unsigned long long)args[0].v.i;
        field = value & mask;
        rest = value & ~mask;
        if (rshift == 0) rotated = field;
        else rotated = ((field << rshift) | (field >> ((unsigned int)size - rshift))) & mask;
        return make_integer_kind((long long)(rest | rotated), kind);
    }
    if (strcmp(upper, "MASKL") == 0 || strcmp(upper, "MASKR") == 0) {
        int kind = 4;
        int bits;
        long long i;
        unsigned long long value;
        if (nargs < 1) ofort_error(I, "%s requires 1 argument", upper);
        if (args[0].type != FVAL_INTEGER)
            ofort_error(I, "%s requires an integer argument", upper);
        if (nargs >= 2) {
            if (args[1].type != FVAL_INTEGER) ofort_error(I, "%s KIND must be integer", upper);
            kind = (int)args[1].v.i;
        }
        bits = integer_kind_bits(kind);
        i = args[0].v.i;
        if (i < 0 || i > bits) ofort_error(I, "%s bit count out of range", upper);
        if (i == 0) return make_integer_kind(0, kind);
        if (i == bits) value = ~0ULL;
        else if (strcmp(upper, "MASKR") == 0) value = (1ULL << (unsigned int)i) - 1ULL;
        else value = (~0ULL) << (unsigned int)(bits - i);
        return make_integer_kind(signed_mask_value(value, bits), kind);
    }
    if (strcmp(upper, "DIGITS") == 0) {
        int kind;
        if (nargs < 1) ofort_error(I, "DIGITS requires 1 argument");
        if (args[0].type == FVAL_INTEGER) {
            kind = args[0].kind ? args[0].kind : 4;
            if (kind == 1) return make_integer(7);
            if (kind == 2) return make_integer(15);
            if (kind == 8) return make_integer(63);
            return make_integer(31);
        }
        if (args[0].type == FVAL_REAL) return make_integer(24);
        if (args[0].type == FVAL_DOUBLE) return make_integer(53);
        ofort_error(I, "DIGITS requires an integer or real argument");
    }
    if (strcmp(upper, "EPSILON") == 0) {
        if (nargs < 1) ofort_error(I, "EPSILON requires 1 argument");
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(DBL_EPSILON);
        if (args[0].type == FVAL_REAL) return make_real(FLT_EPSILON);
        ofort_error(I, "EPSILON requires a real argument");
    }
    if (strcmp(upper, "FRACTION") == 0) {
        int exp = 0;
        double frac;
        if (nargs < 1) ofort_error(I, "FRACTION requires 1 argument");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "FRACTION requires a real argument");
        frac = frexp(val_to_real(args[0]), &exp);
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(frac);
        return make_real(frac);
    }
    if (strcmp(upper, "EXPONENT") == 0) {
        int exp = 0;
        if (nargs < 1) ofort_error(I, "EXPONENT requires 1 argument");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "EXPONENT requires a real argument");
        (void)frexp(val_to_real(args[0]), &exp);
        return make_integer(exp);
    }
    if (strcmp(upper, "RADIX") == 0) {
        if (nargs < 1) ofort_error(I, "RADIX requires 1 argument");
        if (args[0].type != FVAL_INTEGER && args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "RADIX requires an integer or real argument");
        return make_integer(2);
    }
    if (strcmp(upper, "HUGE") == 0) {
        int kind;
        if (nargs < 1) ofort_error(I, "HUGE requires 1 argument");
        if (args[0].type == FVAL_INTEGER) {
            kind = args[0].kind ? args[0].kind : 4;
            if (kind == 1) return make_integer_kind(127, 1);
            if (kind == 2) return make_integer_kind(32767, 2);
            if (kind == 8) return make_integer_kind(LLONG_MAX, 8);
            return make_integer_kind(2147483647LL, 4);
        }
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(DBL_MAX);
        return make_real(FLT_MAX);
    }
    if (strcmp(upper, "TINY") == 0) {
        if (nargs < 1) ofort_error(I, "TINY requires 1 argument");
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(DBL_MIN);
        if (args[0].type == FVAL_REAL) return make_real(FLT_MIN);
        ofort_error(I, "TINY requires a real argument");
    }
    if (strcmp(upper, "NEAREST") == 0) {
        double direction;
        if (nargs < 2) ofort_error(I, "NEAREST requires 2 arguments");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "NEAREST requires a real first argument");
        if (args[1].type != FVAL_INTEGER && args[1].type != FVAL_REAL && args[1].type != FVAL_DOUBLE)
            ofort_error(I, "NEAREST requires a numeric second argument");
        direction = val_to_real(args[1]);
        if (direction == 0.0) ofort_error(I, "NEAREST direction must be nonzero");
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8)
            return make_double(nextafter(val_to_real(args[0]), direction > 0.0 ? INFINITY : -INFINITY));
        return make_real(nextafterf((float)val_to_real(args[0]), direction > 0.0 ? INFINITY : -INFINITY));
    }
    if (strcmp(upper, "PRECISION") == 0) {
        if (nargs < 1) ofort_error(I, "PRECISION requires 1 argument");
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_integer(15);
        if (args[0].type == FVAL_REAL || args[0].type == FVAL_COMPLEX) return make_integer(6);
        ofort_error(I, "PRECISION requires a real or complex argument");
    }
    if (strcmp(upper, "RANGE") == 0) {
        int kind;
        if (nargs < 1) ofort_error(I, "RANGE requires 1 argument");
        kind = args[0].kind ? args[0].kind : 4;
        if (args[0].type == FVAL_INTEGER) {
            if (kind == 1) return make_integer(2);
            if (kind == 2) return make_integer(4);
            if (kind == 8) return make_integer(18);
            return make_integer(9);
        }
        if (args[0].type == FVAL_DOUBLE || args[0].type == FVAL_REAL || args[0].type == FVAL_COMPLEX) {
            if (args[0].type == FVAL_DOUBLE || kind == 8) return make_integer(307);
            return make_integer(37);
        }
        ofort_error(I, "RANGE requires an integer, real, or complex argument");
    }
    if (strcmp(upper, "RRSPACING") == 0) {
        double x, frac, scale;
        int exp = 0;
        if (nargs < 1) ofort_error(I, "RRSPACING requires 1 argument");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "RRSPACING requires a real argument");
        x = val_to_real(args[0]);
        if (x == 0.0) {
            if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(0.0);
            return make_real(0.0);
        }
        frac = fabs(frexp(x, &exp));
        scale = ldexp(1.0, (args[0].type == FVAL_DOUBLE || args[0].kind == 8) ? 53 : 24);
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(frac * scale);
        return make_real(frac * scale);
    }
    if (strcmp(upper, "SPACING") == 0) {
        double x;
        int exp = 0;
        if (nargs < 1) ofort_error(I, "SPACING requires 1 argument");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "SPACING requires a real argument");
        x = val_to_real(args[0]);
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) {
            if (x == 0.0) return make_double(DBL_MIN);
            (void)frexp(x, &exp);
            return make_double(ldexp(1.0, exp - 53));
        }
        if (x == 0.0) return make_real(FLT_MIN);
        (void)frexp((float)x, &exp);
        return make_real(ldexp(1.0, exp - 24));
    }
    if (strcmp(upper, "SCALE") == 0) {
        double x;
        int exponent;
        if (nargs < 2) ofort_error(I, "SCALE requires 2 arguments");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "SCALE requires a real first argument");
        if (args[1].type != FVAL_INTEGER)
            ofort_error(I, "SCALE requires an integer second argument");
        x = val_to_real(args[0]);
        exponent = (int)args[1].v.i;
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(ldexp(x, exponent));
        return make_real(ldexp((float)x, exponent));
    }
    if (strcmp(upper, "SET_EXPONENT") == 0) {
        double x, frac;
        int exponent;
        int old_exp = 0;
        if (nargs < 2) ofort_error(I, "SET_EXPONENT requires 2 arguments");
        if (args[0].type != FVAL_REAL && args[0].type != FVAL_DOUBLE)
            ofort_error(I, "SET_EXPONENT requires a real first argument");
        if (args[1].type != FVAL_INTEGER)
            ofort_error(I, "SET_EXPONENT requires an integer second argument");
        x = val_to_real(args[0]);
        exponent = (int)args[1].v.i;
        if (x == 0.0) {
            if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(0.0);
            return make_real(0.0);
        }
        frac = frexp(x, &old_exp);
        if (args[0].type == FVAL_DOUBLE || args[0].kind == 8) return make_double(ldexp(frac, exponent));
        return make_real(ldexp((float)frac, exponent));
    }
    if (strcmp(upper, "SELECTED_INT_KIND") == 0) {
        long long r;
        if (nargs < 1) ofort_error(I, "SELECTED_INT_KIND requires 1 argument");
        if (args[0].type != FVAL_INTEGER)
            ofort_error(I, "SELECTED_INT_KIND requires an integer argument");
        r = args[0].v.i;
        if (r <= 2) return make_integer(1);
        if (r <= 4) return make_integer(2);
        if (r <= 9) return make_integer(4);
        if (r <= 18) return make_integer(8);
        return make_integer(-1);
    }
    if (strcmp(upper, "SELECTED_REAL_KIND") == 0) {
        int p_idx = intrinsic_arg_index(arg_names, nargs, "p");
        int r_idx = intrinsic_arg_index(arg_names, nargs, "r");
        long long p = 0, r = 0;
        int p_bad, r_bad;
        if (p_idx < 0 && nargs >= 1 && (!arg_names || arg_names[0][0] == '\0')) p_idx = 0;
        if (r_idx < 0 && nargs >= 2 && (!arg_names || arg_names[1][0] == '\0')) r_idx = 1;
        if (p_idx < 0 && r_idx < 0) ofort_error(I, "SELECTED_REAL_KIND requires P or R");
        if (p_idx >= 0) {
            if (args[p_idx].type != FVAL_INTEGER)
                ofort_error(I, "SELECTED_REAL_KIND P must be integer");
            p = args[p_idx].v.i;
        }
        if (r_idx >= 0) {
            if (args[r_idx].type != FVAL_INTEGER)
                ofort_error(I, "SELECTED_REAL_KIND R must be integer");
            r = args[r_idx].v.i;
        }
        p_bad = p > 15;
        r_bad = r > 307;
        if (p_bad && r_bad) return make_integer(-3);
        if (p_bad) return make_integer(-1);
        if (r_bad) return make_integer(-2);
        if (p > 6 || r > 37) return make_integer(8);
        return make_integer(4);
    }
    if (strcmp(upper, "COMMAND_ARGUMENT_COUNT") == 0) {
        return make_integer(I->command_argc);
    }

    /* === Type conversion === */
    if (strcmp(upper, "REAL") == 0 || strcmp(upper, "FLOAT") == 0 || strcmp(upper, "SNGL") == 0) {
        if (nargs < 1) ofort_error(I, "REAL requires 1 argument");
        if (args[0].type == FVAL_COMPLEX) return make_real(args[0].v.cx.re);
        return make_real(val_to_real(args[0]));
    }
    if (strcmp(upper, "INT") == 0) {
        if (nargs < 1) ofort_error(I, "INT requires 1 argument");
        return make_integer((long long)val_to_real(args[0]));
    }
    if (strcmp(upper, "DBLE") == 0 || strcmp(upper, "DFLOAT") == 0) {
        return make_double(val_to_real(args[0]));
    }
    if (strcmp(upper, "DPROD") == 0) {
        if (nargs < 2) ofort_error(I, "DPROD requires 2 arguments");
        return make_double(val_to_real(args[0]) * val_to_real(args[1]));
    }
    if (strcmp(upper, "CMPLX") == 0) {
        double re = nargs > 0 ? val_to_real(args[0]) : 0.0;
        double im = nargs > 1 ? val_to_real(args[1]) : 0.0;
        return make_complex(re, im);
    }
    if (strcmp(upper, "AIMAG") == 0) {
        if (args[0].type == FVAL_COMPLEX) return make_real(args[0].v.cx.im);
        return make_real(0.0);
    }
    if (strcmp(upper, "CONJG") == 0) {
        if (args[0].type == FVAL_COMPLEX) return make_complex(args[0].v.cx.re, -args[0].v.cx.im);
        return make_complex(val_to_real(args[0]), 0.0);
    }
    if (strcmp(upper, "LOGICAL") == 0) {
        return make_logical(val_to_logical(args[0]));
    }

    /* === String intrinsics === */
    if (strcmp(upper, "LEN") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s)
            return make_integer((long long)strlen(args[0].v.s));
        return make_integer(0);
    }
    if (strcmp(upper, "LEN_TRIM") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s) {
            int len = (int)strlen(args[0].v.s);
            while (len > 0 && args[0].v.s[len - 1] == ' ') len--;
            return make_integer(len);
        }
        return make_integer(0);
    }
    if (strcmp(upper, "TRIM") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s) {
            char buf[OFORT_MAX_STRLEN];
            copy_cstr(buf, sizeof(buf), args[0].v.s);
            buf[OFORT_MAX_STRLEN - 1] = '\0';
            int len = (int)strlen(buf);
            while (len > 0 && buf[len - 1] == ' ') len--;
            buf[len] = '\0';
            return make_character(buf);
        }
        return make_character("");
    }
    if (strcmp(upper, "ADJUSTL") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s) {
            const char *p = args[0].v.s;
            while (*p == ' ') p++;
            return make_character(p);
        }
        return make_character("");
    }
    if (strcmp(upper, "ADJUSTR") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s) {
            char buf[OFORT_MAX_STRLEN];
            copy_cstr(buf, sizeof(buf), args[0].v.s);
            buf[OFORT_MAX_STRLEN - 1] = '\0';
            int len = (int)strlen(buf);
            int trail = 0;
            while (len > 0 && buf[len - 1] == ' ') { len--; trail++; }
            if (trail > 0) {
                memmove(buf + trail, buf, len);
                memset(buf, ' ', trail);
                buf[len + trail] = '\0';
            }
            return make_character(buf);
        }
        return make_character("");
    }
    if (strcmp(upper, "INDEX") == 0) {
        if (nargs < 2) ofort_error(I, "INDEX requires 2 arguments");
        if (args[0].type == FVAL_CHARACTER && args[1].type == FVAL_CHARACTER) {
            const char *found = strstr(args[0].v.s, args[1].v.s);
            if (found) return make_integer((long long)(found - args[0].v.s + 1));
        }
        return make_integer(0);
    }
    if (strcmp(upper, "SCAN") == 0) {
        int back_idx = intrinsic_arg_index(arg_names, nargs, "back");
        int back = 0;
        if (nargs < 2) ofort_error(I, "SCAN requires STRING and SET");
        if (args[0].type != FVAL_CHARACTER || args[1].type != FVAL_CHARACTER)
            ofort_error(I, "SCAN requires character arguments");
        if (back_idx < 0 && nargs >= 3) back_idx = 2;
        if (back_idx >= 0) back = val_to_logical(args[back_idx]);
        if (args[0].v.s && args[1].v.s) {
            size_t len = strlen(args[0].v.s);
            if (back) {
                for (size_t i = len; i > 0; i--) {
                    if (strchr(args[1].v.s, args[0].v.s[i - 1]))
                        return make_integer((long long)i);
                }
            } else {
                for (size_t i = 0; i < len; i++) {
                    if (strchr(args[1].v.s, args[0].v.s[i]))
                        return make_integer((long long)i + 1);
                }
            }
        }
        return make_integer(0);
    }
    if (strcmp(upper, "VERIFY") == 0) {
        int back_idx = intrinsic_arg_index(arg_names, nargs, "back");
        int back = 0;
        if (nargs < 2) ofort_error(I, "VERIFY requires STRING and SET");
        if (args[0].type != FVAL_CHARACTER || args[1].type != FVAL_CHARACTER)
            ofort_error(I, "VERIFY requires character arguments");
        if (back_idx < 0 && nargs >= 3) back_idx = 2;
        if (back_idx >= 0) back = val_to_logical(args[back_idx]);
        if (args[0].v.s && args[1].v.s) {
            size_t len = strlen(args[0].v.s);
            if (back) {
                for (size_t i = len; i > 0; i--) {
                    if (!strchr(args[1].v.s, args[0].v.s[i - 1]))
                        return make_integer((long long)i);
                }
            } else {
                for (size_t i = 0; i < len; i++) {
                    if (!strchr(args[1].v.s, args[0].v.s[i]))
                        return make_integer((long long)i + 1);
                }
            }
        }
        return make_integer(0);
    }
    if (strcmp(upper, "CHAR") == 0 || strcmp(upper, "ACHAR") == 0) {
        char buf[2] = {(char)val_to_int(args[0]), '\0'};
        return make_character(buf);
    }
    if (strcmp(upper, "ICHAR") == 0 || strcmp(upper, "IACHAR") == 0) {
        if (args[0].type == FVAL_CHARACTER && args[0].v.s)
            return make_integer((long long)(unsigned char)args[0].v.s[0]);
        return make_integer(0);
    }
    if (strcmp(upper, "REPEAT") == 0) {
        if (nargs < 2) ofort_error(I, "REPEAT requires 2 arguments");
        if (args[0].type == FVAL_CHARACTER && args[0].v.s) {
            int n = (int)val_to_int(args[1]);
            int slen = (int)strlen(args[0].v.s);
            int total = slen * n;
            if (total > OFORT_MAX_STRLEN - 1) total = OFORT_MAX_STRLEN - 1;
            char *buf = (char *)calloc(total + 1, 1);
            for (int i = 0; i < n && (int)strlen(buf) + slen < total + 1; i++)
                strcat(buf, args[0].v.s);
            OfortValue result = make_character(buf);
            free(buf);
            return result;
        }
        return make_character("");
    }

    /* === Array intrinsics === */
    if (strcmp(upper, "SIZE") == 0) {
        if (args[0].type != FVAL_ARRAY) ofort_error(I, "SIZE requires an array argument");
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        if (dim_idx < 0 && nargs >= 2) dim_idx = 1;
        if (dim_idx >= 0) {
            int dim = (int)val_to_int(args[dim_idx]);
            if (dim >= 1 && dim <= args[0].v.arr.n_dims)
                return make_integer(args[0].v.arr.dims[dim - 1]);
            return make_integer(0);
        }
        return make_integer(args[0].v.arr.len);
    }
    if (strcmp(upper, "SHAPE") == 0) {
        if (args[0].type != FVAL_ARRAY) ofort_error(I, "SHAPE requires an array argument");
        int nd = args[0].v.arr.n_dims;
        int dims[1] = {nd};
        OfortValue result = make_array(FVAL_INTEGER, dims, 1);
        for (int i = 0; i < nd; i++) {
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = make_integer(args[0].v.arr.dims[i]);
        }
        return result;
    }
    if (strcmp(upper, "PACK") == 0) {
        OfortValue *array;
        OfortValue *mask;
        OfortValue *vector = NULL;
        int selected = 0;
        int result_len;
        int dims[1];
        OfortValue result;
        int out = 0;

        if (nargs < 2) ofort_error(I, "PACK requires ARRAY and MASK");
        if (args[0].type != FVAL_ARRAY) ofort_error(I, "PACK ARRAY must be an array");
        array = &args[0];
        mask = &args[1];
        if (mask->type == FVAL_ARRAY && mask->v.arr.len != array->v.arr.len)
            ofort_error(I, "PACK mask size mismatch");
        if (nargs >= 3) {
            if (args[2].type != FVAL_ARRAY) ofort_error(I, "PACK VECTOR must be an array");
            vector = &args[2];
        }

        for (int i = 0; i < array->v.arr.len; i++) {
            int take = mask->type == FVAL_ARRAY ? val_to_logical(mask->v.arr.data[i]) : val_to_logical(*mask);
            if (take) selected++;
        }

        result_len = vector ? vector->v.arr.len : selected;
        if (vector && selected > result_len) ofort_error(I, "PACK VECTOR is too short");
        dims[0] = result_len;
        result = make_array(array->v.arr.elem_type, dims, 1);

        for (int i = 0; i < array->v.arr.len; i++) {
            int take = mask->type == FVAL_ARRAY ? val_to_logical(mask->v.arr.data[i]) : val_to_logical(*mask);
            if (!take) continue;
            free_value(&result.v.arr.data[out]);
            result.v.arr.data[out++] = copy_value(array->v.arr.data[i]);
        }
        if (vector) {
            for (int i = out; i < result_len; i++) {
                free_value(&result.v.arr.data[i]);
                result.v.arr.data[i] = copy_value(vector->v.arr.data[i]);
            }
        }
        return result;
    }
    if (strcmp(upper, "UNPACK") == 0) {
        OfortValue *vector;
        OfortValue *mask;
        OfortValue *field;
        OfortValType result_type;
        OfortValue result;
        int vin = 0;

        if (nargs < 3) ofort_error(I, "UNPACK requires VECTOR, MASK, and FIELD");
        if (args[0].type != FVAL_ARRAY) ofort_error(I, "UNPACK VECTOR must be an array");
        if (args[1].type != FVAL_ARRAY) ofort_error(I, "UNPACK MASK must be an array");
        vector = &args[0];
        mask = &args[1];
        field = &args[2];
        if (field->type == FVAL_ARRAY && field->v.arr.len != mask->v.arr.len)
            ofort_error(I, "UNPACK field size mismatch");

        result_type = vector->v.arr.elem_type;
        result = make_array(result_type, mask->v.arr.dims, mask->v.arr.n_dims);

        for (int i = 0; i < mask->v.arr.len; i++) {
            OfortValue *src;
            if (val_to_logical(mask->v.arr.data[i])) {
                if (vin >= vector->v.arr.len) ofort_error(I, "UNPACK VECTOR is too short");
                src = &vector->v.arr.data[vin++];
            } else {
                src = field->type == FVAL_ARRAY ? &field->v.arr.data[i] : field;
            }
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = copy_value(*src);
        }
        return result;
    }
    if (strcmp(upper, "MERGE") == 0) {
        if (nargs < 3) ofort_error(I, "MERGE requires 3 arguments");
        if (args[0].type != FVAL_ARRAY && args[1].type != FVAL_ARRAY && args[2].type != FVAL_ARRAY) {
            return copy_value(val_to_logical(args[2]) ? args[0] : args[1]);
        }

        OfortValue *shape_arg = NULL;
        if (args[2].type == FVAL_ARRAY) shape_arg = &args[2];
        else if (args[0].type == FVAL_ARRAY) shape_arg = &args[0];
        else if (args[1].type == FVAL_ARRAY) shape_arg = &args[1];
        if (!shape_arg) ofort_error(I, "MERGE internal shape error");

        int len = shape_arg->v.arr.len;
        OfortValType result_type = args[0].type == FVAL_ARRAY ? args[0].v.arr.elem_type : args[0].type;
        OfortValue result = make_array(result_type, shape_arg->v.arr.dims, shape_arg->v.arr.n_dims);

        for (int i = 0; i < len; i++) {
            OfortValue *mask = args[2].type == FVAL_ARRAY ? &args[2].v.arr.data[i] : &args[2];
            OfortValue *selected;
            if (val_to_logical(*mask)) {
                selected = args[0].type == FVAL_ARRAY ? &args[0].v.arr.data[i] : &args[0];
            } else {
                selected = args[1].type == FVAL_ARRAY ? &args[1].v.arr.data[i] : &args[1];
            }
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = copy_value(*selected);
        }
        return result;
    }
    if (strcmp(upper, "SUM") == 0) {
        if (args[0].type != FVAL_ARRAY) return copy_value(args[0]);
        double sum = 0;
        if (I->fast_mode &&
            (args[0].v.arr.elem_type == FVAL_REAL || args[0].v.arr.elem_type == FVAL_DOUBLE ||
             args[0].v.arr.elem_type == FVAL_INTEGER)) {
            if (args[0].v.arr.elem_type == FVAL_INTEGER) {
                long long isum = 0;
                for (int i = 0; i < args[0].v.arr.len; i++) isum += args[0].v.arr.data[i].v.i;
                return make_integer(isum);
            }
            for (int i = 0; i < args[0].v.arr.len; i++) sum += args[0].v.arr.data[i].v.r;
            return make_real(sum);
        }
        for (int i = 0; i < args[0].v.arr.len; i++)
            sum += val_to_real(args[0].v.arr.data[i]);
        if (args[0].v.arr.elem_type == FVAL_INTEGER) return make_integer((long long)sum);
        return make_real(sum);
    }
    if (strcmp(upper, "PRODUCT") == 0) {
        if (args[0].type != FVAL_ARRAY) return copy_value(args[0]);
        double prod = 1;
        for (int i = 0; i < args[0].v.arr.len; i++)
            prod *= val_to_real(args[0].v.arr.data[i]);
        if (args[0].v.arr.elem_type == FVAL_INTEGER) return make_integer((long long)prod);
        return make_real(prod);
    }
    if (strcmp(upper, "MAXVAL") == 0) {
        if (args[0].type != FVAL_ARRAY || args[0].v.arr.len == 0)
            ofort_error(I, "MAXVAL requires a non-empty array");
        double mx = val_to_real(args[0].v.arr.data[0]);
        for (int i = 1; i < args[0].v.arr.len; i++) {
            double v = val_to_real(args[0].v.arr.data[i]);
            if (v > mx) mx = v;
        }
        if (args[0].v.arr.elem_type == FVAL_INTEGER) return make_integer((long long)mx);
        return make_real(mx);
    }
    if (strcmp(upper, "MINVAL") == 0) {
        if (args[0].type != FVAL_ARRAY || args[0].v.arr.len == 0)
            ofort_error(I, "MINVAL requires a non-empty array");
        double mn = val_to_real(args[0].v.arr.data[0]);
        for (int i = 1; i < args[0].v.arr.len; i++) {
            double v = val_to_real(args[0].v.arr.data[i]);
            if (v < mn) mn = v;
        }
        if (args[0].v.arr.elem_type == FVAL_INTEGER) return make_integer((long long)mn);
        return make_real(mn);
    }
    if (strcmp(upper, "MAXLOC") == 0 || strcmp(upper, "MINLOC") == 0) {
        int want_max = strcmp(upper, "MAXLOC") == 0;
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        int mask_idx = intrinsic_arg_index(arg_names, nargs, "mask");
        OfortValue *array;
        OfortValue *mask = NULL;
        if (nargs < 1 || args[0].type != FVAL_ARRAY)
            ofort_error(I, "%s requires an array argument", upper);
        array = &args[0];
        if (dim_idx < 0 && mask_idx < 0 && nargs >= 2 &&
            (!arg_names || arg_names[1][0] == '\0') && args[1].type != FVAL_ARRAY)
            dim_idx = 1;
        if (mask_idx < 0 && nargs >= 2) {
            for (int i = 1; i < nargs; i++) {
                if (i != dim_idx && args[i].type == FVAL_ARRAY) {
                    mask_idx = i;
                    break;
                }
            }
        }
        if (mask_idx >= 0) mask = &args[mask_idx];

        if (dim_idx >= 0) {
            int dim = (int)val_to_int(args[dim_idx]);
            if (array->v.arr.n_dims == 1) {
                int rdims[1] = {1};
                OfortValue result = make_array(FVAL_INTEGER, rdims, 1);
                int best_pos = 0;
                double best = 0.0;
                int found = 0;
                if (dim != 1) ofort_error(I, "%s DIM is out of range", upper);
                for (int i = 0; i < array->v.arr.len; i++) {
                    if (mask && !val_to_logical(mask->type == FVAL_ARRAY ? mask->v.arr.data[i] : *mask)) continue;
                    double v = val_to_real(array->v.arr.data[i]);
                    if (!found || (want_max ? v > best : v < best)) {
                        best = v;
                        best_pos = i + 1;
                        found = 1;
                    }
                }
                free_value(&result.v.arr.data[0]);
                result.v.arr.data[0] = make_integer(found ? best_pos : 0);
                return result;
            }
            if (array->v.arr.n_dims == 2) {
                int nrow = array->v.arr.dims[0];
                int ncol = array->v.arr.dims[1];
                if (dim == 1) {
                    int rdims[1] = {ncol};
                    OfortValue result = make_array(FVAL_INTEGER, rdims, 1);
                    for (int j = 0; j < ncol; j++) {
                        int best_pos = 0;
                        double best = 0.0;
                        int found = 0;
                        for (int i = 0; i < nrow; i++) {
                            int idx = i + j * nrow;
                            if (mask && !val_to_logical(mask->type == FVAL_ARRAY ? mask->v.arr.data[idx] : *mask)) continue;
                            double v = val_to_real(array->v.arr.data[idx]);
                            if (!found || (want_max ? v > best : v < best)) {
                                best = v;
                                best_pos = i + 1;
                                found = 1;
                            }
                        }
                        free_value(&result.v.arr.data[j]);
                        result.v.arr.data[j] = make_integer(found ? best_pos : 0);
                    }
                    return result;
                }
                if (dim == 2) {
                    int rdims[1] = {nrow};
                    OfortValue result = make_array(FVAL_INTEGER, rdims, 1);
                    for (int i = 0; i < nrow; i++) {
                        int best_pos = 0;
                        double best = 0.0;
                        int found = 0;
                        for (int j = 0; j < ncol; j++) {
                            int idx = i + j * nrow;
                            if (mask && !val_to_logical(mask->type == FVAL_ARRAY ? mask->v.arr.data[idx] : *mask)) continue;
                            double v = val_to_real(array->v.arr.data[idx]);
                            if (!found || (want_max ? v > best : v < best)) {
                                best = v;
                                best_pos = j + 1;
                                found = 1;
                            }
                        }
                        free_value(&result.v.arr.data[i]);
                        result.v.arr.data[i] = make_integer(found ? best_pos : 0);
                    }
                    return result;
                }
                ofort_error(I, "%s DIM is out of range", upper);
            }
            ofort_error(I, "%s DIM is only implemented for rank 1 or 2 arrays", upper);
        }

        {
            int nd = array->v.arr.n_dims;
            int rdims[1] = {nd};
            OfortValue result = make_array(FVAL_INTEGER, rdims, 1);
            int best_index = -1;
            double best = 0.0;
            for (int i = 0; i < array->v.arr.len; i++) {
                if (mask && !val_to_logical(mask->type == FVAL_ARRAY ? mask->v.arr.data[i] : *mask)) continue;
                double v = val_to_real(array->v.arr.data[i]);
                if (best_index < 0 || (want_max ? v > best : v < best)) {
                    best = v;
                    best_index = i;
                }
            }
            for (int d = 0; d < nd; d++) {
                int sub = 0;
                if (best_index >= 0) {
                    int stride = 1;
                    for (int k = 0; k < d; k++) stride *= array->v.arr.dims[k];
                    sub = (best_index / stride) % array->v.arr.dims[d] + 1;
                }
                free_value(&result.v.arr.data[d]);
                result.v.arr.data[d] = make_integer(sub);
            }
            return result;
        }
    }
    if (strcmp(upper, "DOT_PRODUCT") == 0) {
        if (nargs < 2) ofort_error(I, "DOT_PRODUCT requires 2 arguments");
        if (args[0].type != FVAL_ARRAY || args[1].type != FVAL_ARRAY)
            ofort_error(I, "DOT_PRODUCT requires arrays");
        int len = args[0].v.arr.len < args[1].v.arr.len ? args[0].v.arr.len : args[1].v.arr.len;
        double sum = 0;
        for (int i = 0; i < len; i++)
            sum += val_to_real(args[0].v.arr.data[i]) * val_to_real(args[1].v.arr.data[i]);
        if (args[0].v.arr.elem_type == FVAL_INTEGER) return make_integer((long long)sum);
        return make_real(sum);
    }
    if (strcmp(upper, "MATMUL") == 0) {
        if (nargs < 2) ofort_error(I, "MATMUL requires 2 arguments");
        if (args[0].type != FVAL_ARRAY || args[1].type != FVAL_ARRAY)
            ofort_error(I, "MATMUL requires arrays");
        /* 2D matrix multiply: (m x k) * (k x n) = (m x n) */
        int m, k1, k2, nn;
        if (args[0].v.arr.n_dims == 2 && args[1].v.arr.n_dims == 2) {
            m = args[0].v.arr.dims[0]; k1 = args[0].v.arr.dims[1];
            k2 = args[1].v.arr.dims[0]; nn = args[1].v.arr.dims[1];
            if (k1 != k2) ofort_error(I, "MATMUL: incompatible dimensions");
            int dims[2] = {m, nn};
            OfortValue result = make_array(FVAL_REAL, dims, 2);
            for (int i = 0; i < m; i++) {
                for (int j = 0; j < nn; j++) {
                    double sum = 0;
                    for (int kk = 0; kk < k1; kk++) {
                        /* Column-major: A(i,kk) = data[i + kk*m], B(kk,j) = data[kk + j*k2] */
                        sum += val_to_real(args[0].v.arr.data[i + kk * m]) *
                               val_to_real(args[1].v.arr.data[kk + j * k2]);
                    }
                    free_value(&result.v.arr.data[i + j * m]);
                    result.v.arr.data[i + j * m] = make_real(sum);
                }
            }
            return result;
        }
        /* 1D dot product fallback */
        {
            int len = args[0].v.arr.len < args[1].v.arr.len ? args[0].v.arr.len : args[1].v.arr.len;
            double sum = 0;
            for (int i = 0; i < len; i++)
                sum += val_to_real(args[0].v.arr.data[i]) * val_to_real(args[1].v.arr.data[i]);
            return make_real(sum);
        }
    }
    if (strcmp(upper, "TRANSPOSE") == 0) {
        if (args[0].type != FVAL_ARRAY || args[0].v.arr.n_dims != 2)
            ofort_error(I, "TRANSPOSE requires a 2D array");
        int m = args[0].v.arr.dims[0], nn = args[0].v.arr.dims[1];
        int dims[2] = {nn, m};
        OfortValue result = make_array(args[0].v.arr.elem_type, dims, 2);
        for (int i = 0; i < m; i++) {
            for (int j = 0; j < nn; j++) {
                free_value(&result.v.arr.data[j + i * nn]);
                result.v.arr.data[j + i * nn] = copy_value(args[0].v.arr.data[i + j * m]);
            }
        }
        return result;
    }
    if (strcmp(upper, "RESHAPE") == 0) {
        if (nargs < 2) ofort_error(I, "RESHAPE requires 2 arguments");
        if (args[0].type != FVAL_ARRAY || args[1].type != FVAL_ARRAY)
            ofort_error(I, "RESHAPE requires arrays");
        int new_dims[7], n_new_dims = args[1].v.arr.len;
        int total = 1;
        for (int i = 0; i < n_new_dims && i < 7; i++) {
            new_dims[i] = (int)val_to_int(args[1].v.arr.data[i]);
            total *= new_dims[i];
        }
        OfortValue result = make_array(args[0].v.arr.elem_type, new_dims, n_new_dims);
        int src_len = args[0].v.arr.len;
        for (int i = 0; i < total; i++) {
            free_value(&result.v.arr.data[i]);
            if (i < src_len)
                result.v.arr.data[i] = copy_value(args[0].v.arr.data[i]);
            else
                result.v.arr.data[i] = make_integer(0);
        }
        return result;
    }
    if (strcmp(upper, "SPREAD") == 0) {
        int source_idx = intrinsic_arg_index(arg_names, nargs, "source");
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        int ncopies_idx = intrinsic_arg_index(arg_names, nargs, "ncopies");
        OfortValue *source;
        int source_rank;
        int dim;
        int ncopies;
        int result_dims[7];
        int result_rank;
        OfortValType result_type;
        OfortValue result;

        if (source_idx < 0) source_idx = 0;
        if (dim_idx < 0) dim_idx = 1;
        if (ncopies_idx < 0) ncopies_idx = 2;
        if (nargs <= source_idx || nargs <= dim_idx || nargs <= ncopies_idx)
            ofort_error(I, "SPREAD requires SOURCE, DIM, and NCOPIES");

        source = &args[source_idx];
        source_rank = source->type == FVAL_ARRAY ? source->v.arr.n_dims : 0;
        dim = (int)val_to_int(args[dim_idx]);
        ncopies = (int)val_to_int(args[ncopies_idx]);
        if (ncopies < 0) ncopies = 0;
        if (dim < 1 || dim > source_rank + 1)
            ofort_error(I, "SPREAD DIM is out of range");

        result_rank = source_rank + 1;
        for (int i = 0; i < result_rank; i++) {
            if (i == dim - 1) {
                result_dims[i] = ncopies;
            } else if (source->type == FVAL_ARRAY) {
                int si = i < dim - 1 ? i : i - 1;
                result_dims[i] = source->v.arr.dims[si];
            } else {
                result_dims[i] = ncopies;
            }
        }
        result_type = source->type == FVAL_ARRAY ? source->v.arr.elem_type : source->type;
        result = make_array(result_type, result_dims, result_rank);

        for (int out_idx = 0; out_idx < result.v.arr.len; out_idx++) {
            OfortValue *src = source;
            int src_idx = 0;
            if (source->type == FVAL_ARRAY) {
                int rem = out_idx;
                int src_stride = 1;
                int src_sub[7] = {0};
                for (int d = 0; d < result_rank; d++) {
                    int sub = result_dims[d] ? rem % result_dims[d] : 0;
                    if (result_dims[d]) rem /= result_dims[d];
                    if (d < dim - 1) {
                        src_sub[d] = sub;
                    } else if (d > dim - 1) {
                        src_sub[d - 1] = sub;
                    }
                }
                for (int d = 0; d < source_rank; d++) {
                    src_idx += src_sub[d] * src_stride;
                    src_stride *= source->v.arr.dims[d];
                }
                src = &source->v.arr.data[src_idx];
            }
            free_value(&result.v.arr.data[out_idx]);
            result.v.arr.data[out_idx] = copy_value(*src);
        }
        return result;
    }
    if (strcmp(upper, "EOSHIFT") == 0) {
        int array_idx = intrinsic_arg_index(arg_names, nargs, "array");
        int shift_idx = intrinsic_arg_index(arg_names, nargs, "shift");
        int boundary_idx = intrinsic_arg_index(arg_names, nargs, "boundary");
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        OfortValue *array;
        OfortValue *shift;
        OfortValue *boundary = NULL;
        int dim = 1;
        OfortValue result;

        if (array_idx < 0) array_idx = 0;
        if (shift_idx < 0) shift_idx = 1;
        if (boundary_idx < 0 && nargs > 2 && (!arg_names || arg_names[2][0] == '\0')) boundary_idx = 2;
        if (dim_idx < 0 && nargs > 3 && (!arg_names || arg_names[3][0] == '\0')) dim_idx = 3;
        if (nargs <= array_idx || nargs <= shift_idx)
            ofort_error(I, "EOSHIFT requires ARRAY and SHIFT");
        array = &args[array_idx];
        shift = &args[shift_idx];
        if (array->type != FVAL_ARRAY) ofort_error(I, "EOSHIFT ARRAY must be an array");
        if (boundary_idx >= 0) boundary = &args[boundary_idx];
        if (dim_idx >= 0) dim = (int)val_to_int(args[dim_idx]);
        if (dim < 1 || dim > array->v.arr.n_dims) ofort_error(I, "EOSHIFT DIM is out of range");

        result = make_array(array->v.arr.elem_type, array->v.arr.dims, array->v.arr.n_dims);
        if (array->v.arr.n_dims == 1) {
            int n = array->v.arr.dims[0];
            int sh = (int)val_to_int(*shift);
            for (int i = 0; i < n; i++) {
                int src = i + sh;
                free_value(&result.v.arr.data[i]);
                if (src >= 0 && src < n) {
                    result.v.arr.data[i] = copy_value(array->v.arr.data[src]);
                } else if (boundary) {
                    result.v.arr.data[i] = copy_value(*boundary);
                } else {
                    result.v.arr.data[i] = default_value(array->v.arr.elem_type, 1);
                }
            }
            return result;
        }
        if (array->v.arr.n_dims == 2) {
            int nrow = array->v.arr.dims[0];
            int ncol = array->v.arr.dims[1];
            if (dim == 1) {
                for (int j = 0; j < ncol; j++) {
                    int sh = shift->type == FVAL_ARRAY ? (int)val_to_int(shift->v.arr.data[j]) : (int)val_to_int(*shift);
                    for (int i = 0; i < nrow; i++) {
                        int src_i = i + sh;
                        int idx = i + j * nrow;
                        free_value(&result.v.arr.data[idx]);
                        if (src_i >= 0 && src_i < nrow) {
                            result.v.arr.data[idx] = copy_value(array->v.arr.data[src_i + j * nrow]);
                        } else if (boundary) {
                            result.v.arr.data[idx] = copy_value(*boundary);
                        } else {
                            result.v.arr.data[idx] = default_value(array->v.arr.elem_type, 1);
                        }
                    }
                }
                return result;
            }
            if (dim == 2) {
                for (int i = 0; i < nrow; i++) {
                    int sh = shift->type == FVAL_ARRAY ? (int)val_to_int(shift->v.arr.data[i]) : (int)val_to_int(*shift);
                    for (int j = 0; j < ncol; j++) {
                        int src_j = j + sh;
                        int idx = i + j * nrow;
                        free_value(&result.v.arr.data[idx]);
                        if (src_j >= 0 && src_j < ncol) {
                            result.v.arr.data[idx] = copy_value(array->v.arr.data[i + src_j * nrow]);
                        } else if (boundary) {
                            result.v.arr.data[idx] = copy_value(*boundary);
                        } else {
                            result.v.arr.data[idx] = default_value(array->v.arr.elem_type, 1);
                        }
                    }
                }
                return result;
            }
        }
        ofort_error(I, "EOSHIFT is only implemented for rank 1 or 2 arrays");
    }
    if (strcmp(upper, "CSHIFT") == 0) {
        int array_idx = intrinsic_arg_index(arg_names, nargs, "array");
        int shift_idx = intrinsic_arg_index(arg_names, nargs, "shift");
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        OfortValue *array;
        OfortValue *shift;
        int dim = 1;
        OfortValue result;

        if (array_idx < 0) array_idx = 0;
        if (shift_idx < 0) shift_idx = 1;
        if (dim_idx < 0 && nargs > 2 && (!arg_names || arg_names[2][0] == '\0')) dim_idx = 2;
        if (nargs <= array_idx || nargs <= shift_idx)
            ofort_error(I, "CSHIFT requires ARRAY and SHIFT");
        array = &args[array_idx];
        shift = &args[shift_idx];
        if (array->type != FVAL_ARRAY) ofort_error(I, "CSHIFT ARRAY must be an array");
        if (dim_idx >= 0) dim = (int)val_to_int(args[dim_idx]);
        if (dim < 1 || dim > array->v.arr.n_dims) ofort_error(I, "CSHIFT DIM is out of range");

        result = make_array(array->v.arr.elem_type, array->v.arr.dims, array->v.arr.n_dims);
        if (array->v.arr.n_dims == 1) {
            int n = array->v.arr.dims[0];
            int sh = (int)val_to_int(*shift);
            for (int i = 0; i < n; i++) {
                int src = n ? (i + sh) % n : 0;
                if (src < 0) src += n;
                free_value(&result.v.arr.data[i]);
                result.v.arr.data[i] = copy_value(array->v.arr.data[src]);
            }
            return result;
        }
        if (array->v.arr.n_dims == 2) {
            int nrow = array->v.arr.dims[0];
            int ncol = array->v.arr.dims[1];
            if (dim == 1) {
                for (int j = 0; j < ncol; j++) {
                    int sh = shift->type == FVAL_ARRAY ? (int)val_to_int(shift->v.arr.data[j]) : (int)val_to_int(*shift);
                    for (int i = 0; i < nrow; i++) {
                        int src_i = nrow ? (i + sh) % nrow : 0;
                        int idx = i + j * nrow;
                        if (src_i < 0) src_i += nrow;
                        free_value(&result.v.arr.data[idx]);
                        result.v.arr.data[idx] = copy_value(array->v.arr.data[src_i + j * nrow]);
                    }
                }
                return result;
            }
            if (dim == 2) {
                for (int i = 0; i < nrow; i++) {
                    int sh = shift->type == FVAL_ARRAY ? (int)val_to_int(shift->v.arr.data[i]) : (int)val_to_int(*shift);
                    for (int j = 0; j < ncol; j++) {
                        int src_j = ncol ? (j + sh) % ncol : 0;
                        int idx = i + j * nrow;
                        if (src_j < 0) src_j += ncol;
                        free_value(&result.v.arr.data[idx]);
                        result.v.arr.data[idx] = copy_value(array->v.arr.data[i + src_j * nrow]);
                    }
                }
                return result;
            }
        }
        ofort_error(I, "CSHIFT is only implemented for rank 1 or 2 arrays");
    }
    if (strcmp(upper, "COUNT") == 0) {
        if (args[0].type != FVAL_ARRAY) return make_integer(val_to_logical(args[0]) ? 1 : 0);
        int count = 0;
        for (int i = 0; i < args[0].v.arr.len; i++) {
            if (val_to_logical(args[0].v.arr.data[i])) count++;
        }
        return make_integer(count);
    }
    if (strcmp(upper, "ANY") == 0) {
        if (args[0].type != FVAL_ARRAY) return make_logical(val_to_logical(args[0]));
        for (int i = 0; i < args[0].v.arr.len; i++) {
            if (val_to_logical(args[0].v.arr.data[i])) return make_logical(1);
        }
        return make_logical(0);
    }
    if (strcmp(upper, "ALL") == 0) {
        if (args[0].type != FVAL_ARRAY) return make_logical(val_to_logical(args[0]));
        for (int i = 0; i < args[0].v.arr.len; i++) {
            if (!val_to_logical(args[0].v.arr.data[i])) return make_logical(0);
        }
        return make_logical(1);
    }
    if (strcmp(upper, "ALLOCATED") == 0) {
        if (args[0].type == FVAL_ARRAY) return make_logical(args[0].v.arr.allocated);
        return make_logical(0);
    }
    if (strcmp(upper, "LBOUND") == 0) {
        /* Fortran arrays always start at 1 in our implementation */
        if (intrinsic_arg_index(arg_names, nargs, "dim") >= 0 || nargs >= 2) return make_integer(1);
        if (args[0].type == FVAL_ARRAY) {
            int nd = args[0].v.arr.n_dims;
            int dims[1] = {nd};
            OfortValue result = make_array(FVAL_INTEGER, dims, 1);
            for (int i = 0; i < nd; i++) {
                free_value(&result.v.arr.data[i]);
                result.v.arr.data[i] = make_integer(1);
            }
            return result;
        }
        return make_integer(1);
    }
    if (strcmp(upper, "UBOUND") == 0) {
        if (args[0].type != FVAL_ARRAY) return make_integer(0);
        int dim_idx = intrinsic_arg_index(arg_names, nargs, "dim");
        if (dim_idx < 0 && nargs >= 2) dim_idx = 1;
        if (dim_idx >= 0) {
            int dim = (int)val_to_int(args[dim_idx]);
            if (dim >= 1 && dim <= args[0].v.arr.n_dims)
                return make_integer(args[0].v.arr.dims[dim - 1]);
            return make_integer(0);
        }
        int nd = args[0].v.arr.n_dims;
        int dims[1] = {nd};
        OfortValue result = make_array(FVAL_INTEGER, dims, 1);
        for (int i = 0; i < nd; i++) {
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = make_integer(args[0].v.arr.dims[i]);
        }
        return result;
    }

    ofort_error(I, "Unknown intrinsic function '%s'", name);
    return make_void_val();
}

/* ══════════════════════════════════════════════
 *  PUBLIC API
 * ══════════════════════════════════════════════ */

OfortInterpreter *ofort_create(void) {
    OfortInterpreter *I = (OfortInterpreter *)calloc(1, sizeof(OfortInterpreter));
    if (!I) return NULL;
    I->global_scope = (OfortScope *)calloc(1, sizeof(OfortScope));
    if (!I->global_scope) {
        free(I);
        return NULL;
    }
    set_scope_explicit_typing(I->global_scope);
    I->current_scope = I->global_scope;
    I->node_pool = NULL;
    I->node_pool_len = 0;
    I->node_pool_cap = 0;
    I->warnings_enabled = 1;
    return I;
}

void ofort_destroy(OfortInterpreter *interp) {
    if (!interp) return;
    clear_line_profile(interp);
    /* Free node pool */
    if (interp->node_pool) {
        for (int i = 0; i < interp->node_pool_len; i++) {
            OfortNode *n = interp->node_pool[i];
            if (n->stmts) free(n->stmts);
            free(n);
        }
        free(interp->node_pool);
    }
    /* Free scopes */
    OfortScope *s = interp->current_scope;
    while (s) {
        OfortScope *parent = s->parent;
        for (int i = 0; i < s->n_vars; i++) free_value(&s->vars[i].val);
        free(s);
        s = parent;
    }
    /* Free module vars */
    for (int m = 0; m < interp->n_modules; m++) {
        for (int i = 0; i < interp->modules[m].n_vars; i++) {
            free_value(&interp->modules[m].vars[i].val);
        }
    }
    for (int f = 0; f < interp->n_funcs; f++) {
        for (int i = 0; i < interp->funcs[f].n_saved_vars; i++) {
            free_value(&interp->funcs[f].saved_vars[i].val);
        }
    }
    free(interp);
}

int ofort_execute(OfortInterpreter *interp, const char *source) {
    double total_start;
    double stage_start;
    if (!interp || !source) return -1;
    total_start = ofort_monotonic_seconds();
    clear_timing(interp);
    interp->source = source;
    interp->has_error = 0;
    interp->returning = 0;
    interp->exiting = 0;
    interp->cycling = 0;
    interp->stopping = 0;
    interp->current_line = 0;
    interp->warnings[0] = '\0';
    interp->warn_len = 0;
    interp->procedure_depth = 0;
    if (prepare_line_profile(interp, source) != 0) {
        snprintf(interp->error, sizeof(interp->error), "Out of memory for line profiler");
        interp->has_error = 1;
        return -1;
    }

    if (setjmp(interp->err_jmp) != 0) {
        return -1;
    }

    /* Tokenize */
    stage_start = ofort_monotonic_seconds();
    tokenize(interp, source);
    interp->timing.lex = ofort_monotonic_seconds() - stage_start;
    interp->tok_pos = 0;

    /* Parse */
    stage_start = ofort_monotonic_seconds();
    interp->ast = parse_program(interp);
    interp->timing.parse = ofort_monotonic_seconds() - stage_start;

    /* First pass: register all top-level functions/subroutines/modules */
    stage_start = ofort_monotonic_seconds();
    if (interp->ast && interp->ast->type == FND_BLOCK) {
        for (int i = 0; i < interp->ast->n_stmts; i++) {
            OfortNode *s = interp->ast->stmts[i];
            if (!s) continue;
            if (s->type == FND_SUBROUTINE || s->type == FND_FUNCTION || s->type == FND_MODULE) {
                exec_node(interp, s);
            }
        }
    }
    interp->timing.register_time = ofort_monotonic_seconds() - stage_start;

    /* Second pass: execute everything else */
    stage_start = ofort_monotonic_seconds();
    if (interp->ast && interp->ast->type == FND_BLOCK) {
        for (int i = 0; i < interp->ast->n_stmts; i++) {
            OfortNode *s = interp->ast->stmts[i];
            if (!s) continue;
            if (s->type == FND_SUBROUTINE || s->type == FND_FUNCTION || s->type == FND_MODULE)
                continue; /* already registered */
            exec_node(interp, s);
            if (interp->stopping) break;
        }
    }
    interp->timing.execute = ofort_monotonic_seconds() - stage_start;
    interp->timing.total = ofort_monotonic_seconds() - total_start;

    return interp->has_error ? -1 : 0;
}

int ofort_check(OfortInterpreter *interp, const char *source) {
    double total_start;
    double stage_start;
    if (!interp || !source) return -1;
    total_start = ofort_monotonic_seconds();
    clear_timing(interp);
    interp->source = source;
    interp->has_error = 0;
    interp->returning = 0;
    interp->exiting = 0;
    interp->cycling = 0;
    interp->stopping = 0;
    interp->current_line = 0;
    interp->warnings[0] = '\0';
    interp->warn_len = 0;
    interp->procedure_depth = 0;

    if (setjmp(interp->err_jmp) != 0) {
        return -1;
    }

    stage_start = ofort_monotonic_seconds();
    tokenize(interp, source);
    interp->timing.lex = ofort_monotonic_seconds() - stage_start;
    interp->tok_pos = 0;
    stage_start = ofort_monotonic_seconds();
    interp->ast = parse_program(interp);
    interp->timing.parse = ofort_monotonic_seconds() - stage_start;
    interp->timing.total = ofort_monotonic_seconds() - total_start;
    return interp->has_error ? -1 : 0;
}

void ofort_set_print_expr_statements(OfortInterpreter *interp, int enabled) {
    if (interp) {
        interp->print_expr_statements = enabled ? 1 : 0;
    }
}

void ofort_set_suppress_output(OfortInterpreter *interp, int enabled) {
    if (interp) {
        interp->suppress_output = enabled ? 1 : 0;
    }
}

void ofort_set_implicit_typing(OfortInterpreter *interp, int enabled) {
    if (!interp || !interp->global_scope) return;
    if (enabled) {
        set_scope_legacy_implicit_typing(interp->global_scope);
    } else {
        set_scope_explicit_typing(interp->global_scope);
    }
}

void ofort_set_warnings_enabled(OfortInterpreter *interp, int enabled) {
    if (interp) {
        interp->warnings_enabled = enabled ? 1 : 0;
    }
}

void ofort_set_fast_mode(OfortInterpreter *interp, int enabled) {
    if (interp) {
        interp->fast_mode = enabled ? 1 : 0;
    }
}

void ofort_set_line_profile_enabled(OfortInterpreter *interp, int enabled) {
    if (interp) {
        interp->line_profile_enabled = enabled ? 1 : 0;
        if (!enabled) clear_line_profile(interp);
    }
}

void ofort_set_command_args(OfortInterpreter *interp, int argc, const char *const *argv) {
    if (!interp) return;
    if (argc < 0) argc = 0;
    if (argc > OFORT_MAX_PARAMS) argc = OFORT_MAX_PARAMS;
    interp->command_argc = argc;
    for (int i = 0; i < argc; i++) {
        copy_cstr(interp->command_args[i], sizeof(interp->command_args[i]), argv ? argv[i] : "");
    }
    for (int i = argc; i < OFORT_MAX_PARAMS; i++) {
        interp->command_args[i][0] = '\0';
    }
}

int ofort_dump_variables(OfortInterpreter *interp, const char *const *names,
                         int n_names, char *buf, size_t buf_size) {
    size_t used = 0;
    int count = 0;

    if (!interp || !buf || buf_size == 0) return -1;
    buf[0] = '\0';

    if (names && n_names > 0) {
        for (int i = 0; i < n_names; i++) {
            char value_buf[OFORT_MAX_STRLEN];
            int written;
            OfortVar *var;

            if (!names[i] || names[i][0] == '\0') continue;
            var = find_var(interp, names[i]);
            if (var) {
                value_to_string(interp, var->val, value_buf, sizeof(value_buf));
                written = snprintf(buf + used, buf_size - used, "%s = %s\n", var->name, value_buf);
            } else {
                written = snprintf(buf + used, buf_size - used, "%s: undefined\n", names[i]);
            }
            if (written < 0) return -1;
            if ((size_t)written >= buf_size - used) {
                buf[buf_size - 1] = '\0';
                return count;
            }
            used += (size_t)written;
            count++;
        }
        return count;
    }

    for (OfortScope *scope = interp->current_scope; scope; scope = scope->parent) {
        for (int i = 0; i < scope->n_vars; i++) {
            char value_buf[OFORT_MAX_STRLEN];
            int duplicate = 0;
            int written;

            for (OfortScope *inner = interp->current_scope; inner && inner != scope; inner = inner->parent) {
                for (int j = 0; j < inner->n_vars; j++) {
                    if (str_eq_nocase(inner->vars[j].name, scope->vars[i].name)) {
                        duplicate = 1;
                        break;
                    }
                }
                if (duplicate) break;
            }
            if (duplicate) continue;

            value_to_string(interp, scope->vars[i].val, value_buf, sizeof(value_buf));
            written = snprintf(buf + used, buf_size - used, "%s = %s\n", scope->vars[i].name, value_buf);
            if (written < 0) return -1;
            if ((size_t)written >= buf_size - used) {
                buf[buf_size - 1] = '\0';
                return count;
            }
            used += (size_t)written;
            count++;
        }
    }

    if (count == 0) {
        snprintf(buf, buf_size, "(no variables)\n");
    }
    return count;
}

static const char *value_type_name_lower(OfortValType type) {
    switch (type) {
        case FVAL_INTEGER: return "integer";
        case FVAL_REAL: return "real";
        case FVAL_DOUBLE: return "double precision";
        case FVAL_COMPLEX: return "complex";
        case FVAL_CHARACTER: return "character";
        case FVAL_LOGICAL: return "logical";
        default: return "unknown";
    }
}

static OfortValType variable_display_type(const OfortVar *var) {
    if (!var) return FVAL_VOID;
    if (var->val.type == FVAL_ARRAY) return var->val.v.arr.elem_type;
    return var->val.type;
}

static void variable_shape_string(const OfortVar *var, char *buf, size_t buf_size) {
    size_t used = 0;

    if (!buf || buf_size == 0) return;
    buf[0] = '\0';
    if (!var || var->val.type != FVAL_ARRAY) return;

    used += (size_t)snprintf(buf + used, buf_size - used, "(");
    if (var->val.v.arr.n_dims > 0) {
        for (int i = 0; i < var->val.v.arr.n_dims; i++) {
            int written = snprintf(buf + used, buf_size - used, "%s%d", i > 0 ? "," : "", var->val.v.arr.dims[i]);
            if (written < 0 || (size_t)written >= buf_size - used) {
                buf[buf_size - 1] = '\0';
                return;
            }
            used += (size_t)written;
        }
    } else {
        snprintf(buf + used, buf_size - used, "%d", var->val.v.arr.len);
        used = strlen(buf);
    }
    snprintf(buf + used, buf_size - used, ")");
}

static void variable_shape_extents_string(const OfortVar *var, char *buf, size_t buf_size) {
    size_t used = 0;

    if (!buf || buf_size == 0) return;
    buf[0] = '\0';
    if (!var || var->val.type != FVAL_ARRAY) return;

    if (var->val.v.arr.n_dims > 0) {
        for (int i = 0; i < var->val.v.arr.n_dims; i++) {
            int written = snprintf(buf + used, buf_size - used, "%s%d", i > 0 ? " " : "", var->val.v.arr.dims[i]);
            if (written < 0 || (size_t)written >= buf_size - used) {
                buf[buf_size - 1] = '\0';
                return;
            }
            used += (size_t)written;
        }
    } else {
        snprintf(buf, buf_size, "%d", var->val.v.arr.len);
    }
}

static int append_variable_info_line(OfortInterpreter *interp, const OfortVar *var,
                                     const char *missing_name, char *buf,
                                     size_t buf_size, size_t *used) {
    char value_buf[OFORT_MAX_STRLEN];
    char shape_buf[128];
    int written;

    if (!buf || !used || *used >= buf_size) return -1;
    if (!var) {
        written = snprintf(buf + *used, buf_size - *used, "%s: undefined\n", missing_name ? missing_name : "");
    } else {
        value_to_string(interp, var->val, value_buf, sizeof(value_buf));
        variable_shape_string(var, shape_buf, sizeof(shape_buf));
        written = snprintf(buf + *used, buf_size - *used, "%s %s%s: %s\n",
                           value_type_name_lower(variable_display_type(var)),
                           var->name, shape_buf, value_buf);
    }
    if (written < 0) return -1;
    if ((size_t)written >= buf_size - *used) {
        buf[buf_size - 1] = '\0';
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

int ofort_dump_variable_info(OfortInterpreter *interp, const char *const *names,
                             int n_names, char *buf, size_t buf_size) {
    size_t used = 0;
    int count = 0;

    if (!interp || !buf || buf_size == 0) return -1;
    buf[0] = '\0';

    if (names && n_names > 0) {
        for (int i = 0; i < n_names; i++) {
            int rc;
            if (!names[i] || names[i][0] == '\0') continue;
            rc = append_variable_info_line(interp, find_var(interp, names[i]), names[i], buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
        return count;
    }

    for (OfortScope *scope = interp->current_scope; scope; scope = scope->parent) {
        for (int i = 0; i < scope->n_vars; i++) {
            int duplicate = 0;
            int rc;

            for (OfortScope *inner = interp->current_scope; inner && inner != scope; inner = inner->parent) {
                for (int j = 0; j < inner->n_vars; j++) {
                    if (str_eq_nocase(inner->vars[j].name, scope->vars[i].name)) {
                        duplicate = 1;
                        break;
                    }
                }
                if (duplicate) break;
            }
            if (duplicate) continue;

            rc = append_variable_info_line(interp, &scope->vars[i], NULL, buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
    }

    if (count == 0) {
        snprintf(buf, buf_size, "(no variables)\n");
    }
    return count;
}

static int append_variable_shape_line(const OfortVar *var, const char *missing_name,
                                      char *buf, size_t buf_size, size_t *used) {
    char shape_buf[128];
    int written;

    if (!buf || !used || *used >= buf_size) return -1;
    if (!var) {
        written = snprintf(buf + *used, buf_size - *used, "%s: undefined\n", missing_name ? missing_name : "");
    } else if (var->val.type != FVAL_ARRAY) {
        written = snprintf(buf + *used, buf_size - *used, "%s: scalar\n", var->name);
    } else {
        variable_shape_extents_string(var, shape_buf, sizeof(shape_buf));
        written = snprintf(buf + *used, buf_size - *used, "%s: %s\n", var->name, shape_buf);
    }
    if (written < 0) return -1;
    if ((size_t)written >= buf_size - *used) {
        buf[buf_size - 1] = '\0';
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

int ofort_dump_variable_shapes(OfortInterpreter *interp, const char *const *names,
                               int n_names, char *buf, size_t buf_size) {
    size_t used = 0;
    int count = 0;

    if (!interp || !buf || buf_size == 0) return -1;
    buf[0] = '\0';

    if (names && n_names > 0) {
        for (int i = 0; i < n_names; i++) {
            int rc;
            if (!names[i] || names[i][0] == '\0') continue;
            rc = append_variable_shape_line(find_var(interp, names[i]), names[i], buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
        return count;
    }

    for (OfortScope *scope = interp->current_scope; scope; scope = scope->parent) {
        for (int i = 0; i < scope->n_vars; i++) {
            int duplicate = 0;
            int rc;

            if (scope->vars[i].val.type != FVAL_ARRAY) continue;
            for (OfortScope *inner = interp->current_scope; inner && inner != scope; inner = inner->parent) {
                for (int j = 0; j < inner->n_vars; j++) {
                    if (str_eq_nocase(inner->vars[j].name, scope->vars[i].name)) {
                        duplicate = 1;
                        break;
                    }
                }
                if (duplicate) break;
            }
            if (duplicate) continue;

            rc = append_variable_shape_line(&scope->vars[i], NULL, buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
    }

    if (count == 0) {
        snprintf(buf, buf_size, "(no arrays)\n");
    }
    return count;
}

static int append_variable_size_line(const OfortVar *var, const char *missing_name,
                                     char *buf, size_t buf_size, size_t *used) {
    int written;

    if (!buf || !used || *used >= buf_size) return -1;
    if (!var) {
        written = snprintf(buf + *used, buf_size - *used, "%s: undefined\n", missing_name ? missing_name : "");
    } else if (var->val.type != FVAL_ARRAY) {
        written = snprintf(buf + *used, buf_size - *used, "%s: scalar\n", var->name);
    } else {
        written = snprintf(buf + *used, buf_size - *used, "%s: %d\n", var->name, var->val.v.arr.len);
    }
    if (written < 0) return -1;
    if ((size_t)written >= buf_size - *used) {
        buf[buf_size - 1] = '\0';
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

int ofort_dump_variable_sizes(OfortInterpreter *interp, const char *const *names,
                              int n_names, char *buf, size_t buf_size) {
    size_t used = 0;
    int count = 0;

    if (!interp || !buf || buf_size == 0) return -1;
    buf[0] = '\0';

    if (names && n_names > 0) {
        for (int i = 0; i < n_names; i++) {
            int rc;
            if (!names[i] || names[i][0] == '\0') continue;
            rc = append_variable_size_line(find_var(interp, names[i]), names[i], buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
        return count;
    }

    for (OfortScope *scope = interp->current_scope; scope; scope = scope->parent) {
        for (int i = 0; i < scope->n_vars; i++) {
            int duplicate = 0;
            int rc;

            if (scope->vars[i].val.type != FVAL_ARRAY) continue;
            for (OfortScope *inner = interp->current_scope; inner && inner != scope; inner = inner->parent) {
                for (int j = 0; j < inner->n_vars; j++) {
                    if (str_eq_nocase(inner->vars[j].name, scope->vars[i].name)) {
                        duplicate = 1;
                        break;
                    }
                }
                if (duplicate) break;
            }
            if (duplicate) continue;

            rc = append_variable_size_line(&scope->vars[i], NULL, buf, buf_size, &used);
            if (rc < 0) return -1;
            count++;
            if (rc == 0) return count;
        }
    }

    if (count == 0) {
        snprintf(buf, buf_size, "(no arrays)\n");
    }
    return count;
}

static int append_text_checked(char *buf, size_t buf_size, size_t *used, const char *text) {
    int written;

    if (!buf || !used || !text || *used >= buf_size) return -1;
    written = snprintf(buf + *used, buf_size - *used, "%s", text);
    if (written < 0) return -1;
    if ((size_t)written >= buf_size - *used) {
        buf[buf_size - 1] = '\0';
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

static int append_stats_header(char *buf, size_t buf_size, size_t *used, const char *title) {
    int rc;

    if (*used > 0) {
        rc = append_text_checked(buf, buf_size, used, "\n");
        if (rc <= 0) return rc;
    }
    rc = append_text_checked(buf, buf_size, used, title);
    if (rc <= 0) return rc;
    rc = append_text_checked(buf, buf_size, used, "\n");
    if (rc <= 0) return rc;
    return append_text_checked(
        buf, buf_size, used,
        "name                 size          min          max         mean           sd        first         last\n");
}

static int visible_var_seen_in_inner_scope(OfortInterpreter *interp, OfortScope *scope, const char *name) {
    for (OfortScope *inner = interp->current_scope; inner && inner != scope; inner = inner->parent) {
        for (int j = 0; j < inner->n_vars; j++) {
            if (str_eq_nocase(inner->vars[j].name, name)) return 1;
        }
    }
    return 0;
}

static int array_is_numeric_stats_type(const OfortVar *var, int want_integer) {
    OfortValType type;

    if (!var || var->val.type != FVAL_ARRAY) return 0;
    type = var->val.v.arr.elem_type;
    if (want_integer) return type == FVAL_INTEGER;
    return type == FVAL_REAL || type == FVAL_DOUBLE;
}

static void format_stat_value(double value, int integer_style, char *buf, size_t buf_size) {
    if (integer_style) snprintf(buf, buf_size, "%.0f", value);
    else snprintf(buf, buf_size, "%.7g", value);
}

static int append_array_stats_line(const OfortVar *var, int integer_style,
                                   char *buf, size_t buf_size, size_t *used) {
    int n;
    double min_v;
    double max_v;
    double first_v;
    double last_v;
    double sum = 0.0;
    double sumsq = 0.0;
    double mean;
    double sd;
    double variance;
    char min_buf[64], max_buf[64], mean_buf[64], sd_buf[64], first_buf[64], last_buf[64];
    int written;

    if (!var || var->val.type != FVAL_ARRAY || var->val.v.arr.len <= 0 || !var->val.v.arr.data) return 1;
    n = var->val.v.arr.len;
    first_v = val_to_real(var->val.v.arr.data[0]);
    last_v = val_to_real(var->val.v.arr.data[n - 1]);
    min_v = first_v;
    max_v = first_v;
    for (int i = 0; i < n; i++) {
        double v = val_to_real(var->val.v.arr.data[i]);
        if (v < min_v) min_v = v;
        if (v > max_v) max_v = v;
        sum += v;
        sumsq += v * v;
    }
    mean = sum / n;
    if (n > 1) {
        variance = (sumsq - (sum * sum) / n) / (n - 1);
        sd = sqrt(variance > 0.0 ? variance : 0.0);
    } else {
        sd = 0.0;
    }

    format_stat_value(min_v, integer_style, min_buf, sizeof(min_buf));
    format_stat_value(max_v, integer_style, max_buf, sizeof(max_buf));
    format_stat_value(mean, 0, mean_buf, sizeof(mean_buf));
    format_stat_value(sd, 0, sd_buf, sizeof(sd_buf));
    format_stat_value(first_v, integer_style, first_buf, sizeof(first_buf));
    format_stat_value(last_v, integer_style, last_buf, sizeof(last_buf));

    written = snprintf(buf + *used, buf_size - *used,
                       "%-16s %8d %12s %12s %12s %12s %12s %12s\n",
                       var->name, n, min_buf, max_buf, mean_buf, sd_buf, first_buf, last_buf);
    if (written < 0) return -1;
    if ((size_t)written >= buf_size - *used) {
        buf[buf_size - 1] = '\0';
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

static int append_stats_group_for_names(OfortInterpreter *interp, const char *const *names, int n_names,
                                        int want_integer, char *buf, size_t buf_size, size_t *used,
                                        int *count) {
    int header_printed = 0;

    for (int i = 0; i < n_names; i++) {
        OfortVar *var = names[i] ? find_var(interp, names[i]) : NULL;
        int rc;
        if (!array_is_numeric_stats_type(var, want_integer)) continue;
        if (!header_printed) {
            rc = append_stats_header(buf, buf_size, used, want_integer ? "integer arrays" : "real arrays");
            if (rc <= 0) return rc;
            header_printed = 1;
        }
        rc = append_array_stats_line(var, want_integer, buf, buf_size, used);
        if (rc < 0) return -1;
        (*count)++;
        if (rc == 0) return 0;
    }
    return 1;
}

static int append_stats_group_for_visible_arrays(OfortInterpreter *interp, int want_integer,
                                                 char *buf, size_t buf_size, size_t *used, int *count) {
    int header_printed = 0;

    for (OfortScope *scope = interp->current_scope; scope; scope = scope->parent) {
        for (int i = 0; i < scope->n_vars; i++) {
            int rc;
            if (visible_var_seen_in_inner_scope(interp, scope, scope->vars[i].name)) continue;
            if (!array_is_numeric_stats_type(&scope->vars[i], want_integer)) continue;
            if (!header_printed) {
                rc = append_stats_header(buf, buf_size, used, want_integer ? "integer arrays" : "real arrays");
                if (rc <= 0) return rc;
                header_printed = 1;
            }
            rc = append_array_stats_line(&scope->vars[i], want_integer, buf, buf_size, used);
            if (rc < 0) return -1;
            (*count)++;
            if (rc == 0) return 0;
        }
    }
    return 1;
}

int ofort_dump_variable_stats(OfortInterpreter *interp, const char *const *names,
                              int n_names, char *buf, size_t buf_size) {
    size_t used = 0;
    int count = 0;
    int rc;

    if (!interp || !buf || buf_size == 0) return -1;
    buf[0] = '\0';

    if (names && n_names > 0) {
        rc = append_stats_group_for_names(interp, names, n_names, 1, buf, buf_size, &used, &count);
        if (rc <= 0) return rc < 0 ? -1 : count;
        rc = append_stats_group_for_names(interp, names, n_names, 0, buf, buf_size, &used, &count);
        if (rc <= 0) return rc < 0 ? -1 : count;

        for (int i = 0; i < n_names; i++) {
            OfortVar *var = names[i] ? find_var(interp, names[i]) : NULL;
            int written;
            if (!names[i] || names[i][0] == '\0') continue;
            if (!var) {
                written = snprintf(buf + used, buf_size - used, "%s: undefined\n", names[i]);
            } else if (var->val.type != FVAL_ARRAY) {
                written = snprintf(buf + used, buf_size - used, "%s: scalar\n", var->name);
            } else if (!array_is_numeric_stats_type(var, 1) && !array_is_numeric_stats_type(var, 0)) {
                written = snprintf(buf + used, buf_size - used, "%s: nonnumeric\n", var->name);
            } else {
                continue;
            }
            if (written < 0) return -1;
            if ((size_t)written >= buf_size - used) {
                buf[buf_size - 1] = '\0';
                return count;
            }
            used += (size_t)written;
        }
        if (count == 0 && used == 0) snprintf(buf, buf_size, "(no numeric arrays)\n");
        return count;
    }

    rc = append_stats_group_for_visible_arrays(interp, 1, buf, buf_size, &used, &count);
    if (rc <= 0) return rc < 0 ? -1 : count;
    rc = append_stats_group_for_visible_arrays(interp, 0, buf, buf_size, &used, &count);
    if (rc <= 0) return rc < 0 ? -1 : count;

    if (count == 0) {
        snprintf(buf, buf_size, "(no numeric arrays)\n");
    }
    return count;
}

const char *ofort_get_output(OfortInterpreter *interp) {
    return interp ? interp->output : "";
}

const char *ofort_get_error(OfortInterpreter *interp) {
    return interp ? interp->error : "";
}

const char *ofort_get_warnings(OfortInterpreter *interp) {
    return interp ? interp->warnings : "";
}

int ofort_get_timing(OfortInterpreter *interp, OfortTiming *timing) {
    if (!interp || !timing) return -1;
    *timing = interp->timing;
    return 0;
}

int ofort_get_line_profile(OfortInterpreter *interp, OfortLineProfileEntry *entries,
                           int max_entries, int *n_entries) {
    int count = 0;
    if (!interp || !n_entries) return -1;
    for (int line = 1; line <= interp->line_profile_nlines; line++) {
        if (!interp->line_profile_counts || interp->line_profile_counts[line] <= 0) continue;
        if (entries && count < max_entries) {
            entries[count].line = line;
            entries[count].count = interp->line_profile_counts[line];
            entries[count].seconds = interp->line_profile_seconds ? interp->line_profile_seconds[line] : 0.0;
        }
        count++;
    }
    *n_entries = count;
    return 0;
}

void ofort_reset(OfortInterpreter *interp) {
    if (!interp) return;
    interp->output[0] = '\0';
    interp->out_len = 0;
    interp->error[0] = '\0';
    interp->warnings[0] = '\0';
    interp->warn_len = 0;
    interp->has_error = 0;
    interp->returning = 0;
    interp->exiting = 0;
    interp->cycling = 0;
    interp->stopping = 0;
    interp->current_line = 0;
    interp->procedure_depth = 0;
    clear_timing(interp);
    clear_line_profile(interp);
}
