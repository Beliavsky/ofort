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
#include <time.h>

/* ══════════════════════════════════════════════
 *  Interpreter state
 * ══════════════════════════════════════════════ */

typedef struct {
    char name[256];
    OfortValue val;
    int is_parameter; /* PARAMETER = const */
    int intent;       /* 0=none,1=IN,2=OUT,3=INOUT */
} OfortVar;

typedef struct OfortScope {
    OfortVar vars[OFORT_MAX_VARS];
    int n_vars;
    int implicit_none;
    struct OfortScope *parent;
} OfortScope;

typedef struct {
    char name[256];
    OfortNode *node;
    int is_function; /* 1=function, 0=subroutine */
    char module_name[256]; /* "" if not in a module */
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
    int n_vars;
    OfortTypeDef types[32];
    int n_types;
} OfortModule;

typedef struct {
    int unit;
    char path[512];
} OfortUnitFile;

struct OfortInterpreter {
    /* output */
    char output[OFORT_MAX_OUTPUT];
    int out_len;
    char error[4096];
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
    /* node pool for memory management */
    OfortNode **node_pool;
    int node_pool_len;
    int node_pool_cap;
};

/* ── Forward declarations ────────────────────── */
static void ofort_error(OfortInterpreter *I, const char *fmt, ...);
static OfortValue eval_node(OfortInterpreter *I, OfortNode *n);
static void exec_node(OfortInterpreter *I, OfortNode *n);
static OfortValue call_intrinsic(OfortInterpreter *I, const char *name, OfortValue *args, int nargs);
static int is_intrinsic(const char *name);

/* ── Helpers ─────────────────────────────────── */

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

/* ── Value constructors ─────────────────────── */
static OfortValue make_integer(long long v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_INTEGER; r.v.i = v; return r;
}
static OfortValue make_real(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_REAL; r.v.r = v; return r;
}
static OfortValue make_double(double v) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_DOUBLE; r.v.r = v; return r;
}
static OfortValue make_complex(double re, double im) {
    OfortValue r; memset(&r, 0, sizeof(r));
    r.type = FVAL_COMPLEX; r.v.cx.re = re; r.v.cx.im = im; return r;
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
    I->current_scope = s;
    return s;
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
                val = coerce_assignment_value(I, name, ps->vars[i].val.type, val);
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
    if (s->n_vars >= OFORT_MAX_VARS) ofort_error(I, "Too many variables");
    OfortVar *v = &s->vars[s->n_vars++];
    strncpy(v->name, name, 255);
    v->val = val;
    v->is_parameter = 0;
    v->intent = 0;
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
            return &s->vars[i];
        }
    }
    OfortVar *v = &s->vars[s->n_vars++];
    strncpy(v->name, name, 255);
    v->val = val;
    v->is_parameter = 0;
    v->intent = 0;
    return v;
}

/* ── Function lookup ─────────────────────────── */
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
    strncpy(f->name, name, 255);
    f->node = node;
    f->is_function = is_function;
    f->module_name[0] = '\0';
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
            } else {
                t->type = FTOK_INT_LIT;
                t->int_val = strtoll(numbuf, NULL, 10);
                t->num_val = (double)t->int_val;
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
        n->line = t->line;
        return n;
    }
    /* real literal */
    if (t->type == FTOK_REAL_LIT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_REAL_LIT);
        n->num_val = t->num_val;
        n->val_type = FVAL_REAL;
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
        strncpy(n->str_val, t->str_val, OFORT_MAX_STRLEN - 1);
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
    if (t->type == FTOK_IDENT) {
        advance(I);
        OfortNode *n = alloc_node(I, FND_IDENT);
        strncpy(n->name, t->str_val, 255);
        n->line = t->line;

        /* function call / array reference: ident( ... ) */
        while (check(I, FTOK_LPAREN)) {
            advance(I);
            /* check if this is a slice: ident(start:end) */
            /* Parse argument list */
            OfortNode *call_node;
            /* determine if function call or array ref later at eval time */
            call_node = alloc_node(I, FND_FUNC_CALL);
            strncpy(call_node->name, n->name, 255);
            call_node->line = n->line;
            call_node->stmts = NULL;
            call_node->n_stmts = 0;
            int cap2 = 0;

            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                /* Check for slice notation: expr:expr or expr:expr:expr or just : */
                OfortNode *arg = parse_expr(I);
                if (check(I, FTOK_COLON)) {
                    advance(I);
                    OfortNode *slice = alloc_node(I, FND_SLICE);
                    slice->children[0] = arg;
                    slice->n_children = 2;
                    if (!check(I, FTOK_RPAREN) && !check(I, FTOK_COMMA)) {
                        slice->children[1] = parse_expr(I);
                    } else {
                        slice->children[1] = NULL; /* open-ended slice */
                    }
                    /* optional stride: start:end:stride */
                    if (check(I, FTOK_COLON)) {
                        advance(I);
                        slice->children[2] = parse_expr(I);
                        slice->n_children = 3;
                    }
                    arg = slice;
                }
                if (call_node->n_stmts >= cap2) {
                    cap2 = cap2 ? cap2 * 2 : 8;
                    call_node->stmts = (OfortNode **)realloc(call_node->stmts, sizeof(OfortNode *) * cap2);
                }
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
            strncpy(mem->name, mt->str_val, 255);
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
    int is_allocatable = 0;
    int is_parameter = 0;
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
                OfortToken *lt = expect(I, FTOK_INT_LIT);
                char_len = (int)lt->int_val;
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
        } else if (check(I, FTOK_PARAMETER)) {
            advance(I);
            is_parameter = 1;
        } else if (check(I, FTOK_INTENT)) {
            advance(I);
            expect(I, FTOK_LPAREN);
            if (check(I, FTOK_IN)) { advance(I); intent = 1; }
            else if (check(I, FTOK_OUT)) { advance(I); intent = 2; }
            else if (check(I, FTOK_INOUT)) { advance(I); intent = 3; }
            expect(I, FTOK_RPAREN);
        } else if (check(I, FTOK_SAVE)) {
            advance(I); /* just note it */
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
        strncpy(decl->name, name_tok->str_val, 255);
        decl->val_type = vtype;
        decl->char_len = char_len;
        decl->is_allocatable = is_allocatable;
        decl->is_parameter = is_parameter;
        decl->intent = intent;
        decl->line = name_tok->line;

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

    /* DO i = start, end [, step] */
    OfortNode *n = alloc_node(I, FND_DO_LOOP);
    n->line = dot->line;

    /* loop variable */
    OfortToken *var_tok = expect(I, FTOK_IDENT);
    strncpy(n->name, var_tok->str_val, 255);
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
        strncpy(n->format_str, peek(I)->str_val, 511);
        advance(I);
    } else {
        n->format_str[0] = '\0';
    }

    /* consume comma after format */
    if (check(I, FTOK_COMMA)) advance(I);

    /* parse output items */
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

static OfortNode *parse_write(OfortInterpreter *I) {
    OfortToken *wt = advance(I); /* WRITE */
    OfortNode *n = alloc_node(I, FND_WRITE);
    n->line = wt->line;
    n->stmts = NULL;
    n->n_stmts = 0;
    int cap = 0;
    n->format_str[0] = '\0';

    /* WRITE(unit, fmt) or WRITE(unit, fmt=...) */
    expect(I, FTOK_LPAREN);
    /* unit: * or number */
    if (check(I, FTOK_STAR)) {
        advance(I);
    } else {
        n->children[0] = parse_expr(I);
        n->n_children = 1;
    }
    if (check(I, FTOK_COMMA)) {
        advance(I);
    }
    /* control list: positional fmt or named fmt=... */
    while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
        if (check(I, FTOK_IDENT) && peek_ahead(I, 1)->type == FTOK_ASSIGN) {
            OfortToken *name = advance(I);
            advance(I); /* = */
            if (str_eq_nocase(name->str_val, "fmt")) {
                if (check(I, FTOK_STAR)) {
                    advance(I);
                } else if (check(I, FTOK_STRING_LIT)) {
                    strncpy(n->format_str, peek(I)->str_val, 511);
                    advance(I);
                } else if (check(I, FTOK_INT_LIT)) {
                    advance(I); /* format label number, ignore */
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
            advance(I);
        } else if (check(I, FTOK_STRING_LIT)) {
            strncpy(n->format_str, peek(I)->str_val, 511);
            advance(I);
        } else if (check(I, FTOK_INT_LIT)) {
            advance(I); /* format label number, ignore */
        } else {
            parse_expr(I);
        }
        if (check(I, FTOK_COMMA)) {
            advance(I);
        } else {
            break;
        }
    }
    expect(I, FTOK_RPAREN);

    /* output items */
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

static OfortNode *parse_read_stmt(OfortInterpreter *I) {
    advance(I); /* READ */
    OfortNode *n = alloc_node(I, FND_READ_STMT);
    n->stmts = NULL; n->n_stmts = 0;
    int cap = 0;
    n->format_str[0] = '\0';

    /* READ(unit, fmt) or READ *, ... */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        if (check(I, FTOK_STAR)) {
            advance(I);
        } else {
            n->children[0] = parse_expr(I);
            n->n_children = 1;
        }
        expect(I, FTOK_COMMA);
        if (check(I, FTOK_STAR)) advance(I);
        else if (check(I, FTOK_STRING_LIT)) {
            strncpy(n->format_str, peek(I)->str_val, 511);
            advance(I);
        }
        expect(I, FTOK_RPAREN);
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
    strncpy(n->name, name->str_val, 255);
    n->line = st->line;
    n->n_params = 0;

    /* parameter list */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *param = expect(I, FTOK_IDENT);
            strncpy(n->param_names[n->n_params], param->str_val, 255);
            n->param_types[n->n_params] = FVAL_VOID; /* resolved later */
            n->param_intents[n->n_params] = 0;
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

static OfortNode *parse_function(OfortInterpreter *I) {
    OfortToken *ft = advance(I); /* FUNCTION */
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_FUNCTION);
    strncpy(n->name, name->str_val, 255);
    n->line = ft->line;
    n->n_params = 0;
    n->result_name[0] = '\0';

    /* parameter list */
    if (check(I, FTOK_LPAREN)) {
        advance(I);
        while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
            OfortToken *param = expect(I, FTOK_IDENT);
            strncpy(n->param_names[n->n_params], param->str_val, 255);
            n->param_types[n->n_params] = FVAL_VOID;
            n->param_intents[n->n_params] = 0;
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
        strncpy(n->result_name, res->str_val, 255);
        expect(I, FTOK_RPAREN);
    }
    skip_newlines(I);

    /* body */
    n->children[0] = parse_block_until_end(I, "FUNCTION");
    n->n_children = 1;
    consume_end(I, "FUNCTION");
    return n;
}

static OfortNode *parse_module(OfortInterpreter *I) {
    OfortToken *mt = advance(I); /* MODULE */
    OfortToken *name = expect(I, FTOK_IDENT);

    OfortNode *n = alloc_node(I, FND_MODULE);
    strncpy(n->name, name->str_val, 255);
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
    strncpy(n->name, name->str_val, 255);
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
    n->line = at->line;
    expect(I, FTOK_LPAREN);
    /* parse: array_name(dim1, dim2, ...) */
    OfortToken *name = expect(I, FTOK_IDENT);
    strncpy(n->name, name->str_val, 255);
    expect(I, FTOK_LPAREN);
    n->stmts = NULL; n->n_stmts = 0;
    int cap = 0;
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
    expect(I, FTOK_RPAREN);
    return n;
}

static OfortNode *parse_deallocate(OfortInterpreter *I) {
    OfortToken *dt = advance(I); /* DEALLOCATE */
    OfortNode *n = alloc_node(I, FND_DEALLOCATE);
    n->line = dt->line;
    expect(I, FTOK_LPAREN);
    OfortToken *name = expect(I, FTOK_IDENT);
    strncpy(n->name, name->str_val, 255);
    expect(I, FTOK_RPAREN);
    return n;
}

static OfortNode *parse_statement(OfortInterpreter *I) {
    skip_newlines(I);
    OfortToken *t = peek(I);
    if (t->type == FTOK_EOF) return NULL;

    /* IMPLICIT NONE */
    if (t->type == FTOK_IMPLICIT) {
        advance(I);
        if (check(I, FTOK_NONE)) advance(I);
        OfortNode *n = alloc_node(I, FND_IMPLICIT_NONE);
        n->line = t->line;
        return n;
    }

    /* USE module_name */
    if (t->type == FTOK_USE) {
        advance(I);
        OfortToken *mn = expect(I, FTOK_IDENT);
        OfortNode *n = alloc_node(I, FND_USE);
        strncpy(n->name, mn->str_val, 255);
        n->line = t->line;
        return n;
    }

    /* CONTAINS */
    if (t->type == FTOK_CONTAINS) {
        advance(I);
        /* just skip it; subroutines/functions follow */
        return NULL;
    }

    /* declarations */
    if (is_type_keyword(t->type)) {
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
        if (name) strncpy(n->name, name->str_val, 255);
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
        strncpy(n->name, name->str_val, 255);
        n->line = ct->line;
        n->stmts = NULL; n->n_stmts = 0;
        int cap = 0;
        if (check(I, FTOK_LPAREN)) {
            advance(I);
            while (!check(I, FTOK_RPAREN) && !check(I, FTOK_EOF)) {
                OfortNode *arg = parse_expr(I);
                if (n->n_stmts >= cap) {
                    cap = cap ? cap * 2 : 8;
                    n->stmts = (OfortNode **)realloc(n->stmts, sizeof(OfortNode *) * cap);
                }
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
        OfortNode *n = alloc_node(I, FND_EXIT);
        n->line = t->line;
        return n;
    }

    /* CYCLE */
    if (t->type == FTOK_CYCLE) {
        advance(I);
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
            strncpy(n->str_val, peek(I)->str_val, OFORT_MAX_STRLEN - 1);
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
    if (t->type == FTOK_END) return NULL;

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

static OfortValue make_array(OfortValType elem_type, int *dims, int n_dims) {
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
        v.v.arr.data[i] = default_value(elem_type, 1);
    return v;
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

    return make_array(n->val_type, dims, ndims);
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
    strncpy(entry->path, path, sizeof(entry->path) - 1);
    entry->path[sizeof(entry->path) - 1] = '\0';
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
            int width = 0;
            p++;
            while (isdigit((unsigned char)*p)) { width = width * 10 + (*p - '0'); p++; }
            if (*p == '.') { p++; while (isdigit((unsigned char)*p)) p++; }
            for (int r = 0; r < repeat && *vidx < nvals; r++, (*vidx)++) {
                char buf[64];
                snprintf(buf, sizeof(buf), "%*lld", width, val_to_int(vals[*vidx]));
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
        return make_integer(n->int_val);

    case FND_REAL_LIT:
        if (n->val_type == FVAL_DOUBLE) return make_double(n->num_val);
        return make_real(n->num_val);

    case FND_STRING_LIT:
        return make_character(n->str_val);

    case FND_LOGICAL_LIT:
        return make_logical(n->bool_val);

    case FND_COMPLEX_LIT: {
        double re = val_to_real(eval_node(I, n->children[0]));
        double im = val_to_real(eval_node(I, n->children[1]));
        return make_complex(re, im);
    }

    case FND_IDENT: {
        OfortVar *v = find_var(I, n->name);
        if (!v) ofort_error(I, "Undefined variable '%s' at line %d", n->name, n->line);
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
        int has_slice = 0;

        /* check for slices */
        for (int i = 0; i < nargs; i++) {
            if (n->stmts[i]->type == FND_SLICE) { has_slice = 1; break; }
        }

        /* Check if this is an array variable reference */
        OfortVar *var = find_var(I, n->name);
        if (var && var->val.type == FVAL_ARRAY) {
            if (has_slice) {
                /* Array slice: arr(start:end) */
                /* For now support 1-D slicing */
                OfortNode *slice = n->stmts[0];
                OfortValue start_v = eval_node(I, slice->children[0]);
                int start = (int)val_to_int(start_v);
                int end;
                if (slice->children[1]) {
                    OfortValue end_v = eval_node(I, slice->children[1]);
                    end = (int)val_to_int(end_v);
                    free_value(&end_v);
                } else {
                    end = var->val.v.arr.dims[0];
                }
                free_value(&start_v);
                int step = 1;
                if (slice->n_children >= 3 && slice->children[2]) {
                    OfortValue step_v = eval_node(I, slice->children[2]);
                    step = (int)val_to_int(step_v);
                    free_value(&step_v);
                }
                /* 1-based indexing */
                int count = 0;
                for (int idx = start; step > 0 ? idx <= end : idx >= end; idx += step) count++;
                int dims[1] = {count};
                OfortValue result = make_array(var->val.v.arr.elem_type, dims, 1);
                int ri = 0;
                for (int idx = start; step > 0 ? idx <= end : idx >= end; idx += step) {
                    int ai = idx - 1; /* convert to 0-based */
                    if (ai >= 0 && ai < var->val.v.arr.len) {
                        free_value(&result.v.arr.data[ri]);
                        result.v.arr.data[ri] = copy_value(var->val.v.arr.data[ai]);
                    }
                    ri++;
                }
                return result;
            }

            /* Array element access: 1-based indexing */
            int index = 0;
            if (nargs == 1) {
                /* 1-D or linear index */
                for (int i = 0; i < nargs; i++) args[i] = eval_node(I, n->stmts[i]);
                index = (int)val_to_int(args[0]) - 1; /* convert to 0-based */
                for (int i = 0; i < nargs; i++) free_value(&args[i]);
            } else {
                /* Multi-dimensional: column-major (Fortran order) */
                for (int i = 0; i < nargs; i++) args[i] = eval_node(I, n->stmts[i]);
                index = 0;
                int stride = 1;
                for (int i = 0; i < nargs; i++) {
                    int idx = (int)val_to_int(args[i]) - 1;
                    index += idx * stride;
                    if (i < var->val.v.arr.n_dims)
                        stride *= var->val.v.arr.dims[i];
                }
                for (int i = 0; i < nargs; i++) free_value(&args[i]);
            }
            if (index < 0 || index >= var->val.v.arr.len)
                ofort_error(I, "Array index out of bounds: %d (size %d)", index + 1, var->val.v.arr.len);
            return copy_value(var->val.v.arr.data[index]);
        }

        /* Evaluate all args */
        for (int i = 0; i < nargs; i++) args[i] = eval_node(I, n->stmts[i]);

        /* Check for intrinsic */
        if (is_intrinsic(n->name)) {
            OfortValue result = call_intrinsic(I, n->name, args, nargs);
            for (int i = 0; i < nargs; i++) free_value(&args[i]);
            return result;
        }

        /* Check for user function */
        OfortFunc *func = find_func(I, n->name);
        if (func && func->is_function) {
            OfortNode *fn = func->node;
            push_scope(I);
            /* Bind parameters */
            for (int i = 0; i < fn->n_params && i < nargs; i++) {
                declare_var(I, fn->param_names[i], copy_value(args[i]));
            }
            /* Set up result variable */
            const char *res_name = fn->result_name[0] ? fn->result_name : fn->name;
            declare_var(I, res_name, make_integer(0));

            /* Execute body */
            exec_node(I, fn->children[0]);
            I->returning = 0;

            /* Get result */
            OfortVar *rv = find_var(I, res_name);
            OfortValue result = rv ? copy_value(rv->val) : make_void_val();

            /* Handle INTENT(OUT/INOUT) — copy back */
            for (int i = 0; i < fn->n_params && i < nargs; i++) {
                if (fn->param_intents[i] == 2 || fn->param_intents[i] == 3) {
                    OfortVar *pv = find_var(I, fn->param_names[i]);
                    if (pv && n->stmts[i]->type == FND_IDENT) {
                        free_value(&args[i]);
                        args[i] = copy_value(pv->val);
                    }
                }
            }

            pop_scope(I);

            /* Write back OUT/INOUT args */
            for (int i = 0; i < fn->n_params && i < nargs; i++) {
                if (fn->param_intents[i] == 2 || fn->param_intents[i] == 3) {
                    if (n->stmts[i]->type == FND_IDENT) {
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
            strncpy(v.v.dt.type_name, td->name, 63);
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

/* Execute statement node */
static void exec_node(OfortInterpreter *I, OfortNode *n) {
    if (!n) return;
    if (I->returning || I->exiting || I->cycling || I->stopping) return;
    if (n->line > 0) I->current_line = n->line;

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
        strncpy(mod->name, n->name, 127);
        mod->n_funcs = 0;
        mod->n_vars = 0;
        mod->n_types = 0;

        /* Execute the module body to register functions and declarations */
        push_scope(I);
        OfortNode *body = n->children[0];
        if (body) {
            for (int i = 0; i < body->n_stmts; i++) {
                OfortNode *s = body->stmts[i];
                if (s->type == FND_SUBROUTINE || s->type == FND_FUNCTION) {
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
        if (!mod) ofort_error(I, "Module '%s' not found", n->name);
        /* import variables */
        for (int i = 0; i < mod->n_vars; i++) {
            declare_var(I, mod->vars[i].name, copy_value(mod->vars[i].val));
        }
        break;
    }

    case FND_TYPE_DEF: {
        /* Register type definition */
        if (I->n_type_defs >= 64) ofort_error(I, "Too many type definitions");
        OfortTypeDef *td = &I->type_defs[I->n_type_defs++];
        strncpy(td->name, n->name, 127);
        td->n_fields = 0;
        /* Parse field declarations from stmts */
        for (int i = 0; i < n->n_stmts; i++) {
            OfortNode *s = n->stmts[i];
            if (s->type == FND_BLOCK) {
                /* declaration block */
                for (int j = 0; j < s->n_stmts; j++) {
                    OfortNode *d = s->stmts[j];
                    if ((d->type == FND_VARDECL || d->type == FND_PARAMDECL) && td->n_fields < OFORT_MAX_FIELDS) {
                        strncpy(td->field_names[td->n_fields], d->name, 63);
                        td->field_types[td->n_fields] = d->val_type;
                        td->field_char_lens[td->n_fields] = d->char_len;
                        td->n_fields++;
                    }
                }
            } else if ((s->type == FND_VARDECL || s->type == FND_PARAMDECL) && td->n_fields < OFORT_MAX_FIELDS) {
                strncpy(td->field_names[td->n_fields], s->name, 63);
                td->field_types[td->n_fields] = s->val_type;
                td->field_char_lens[td->n_fields] = s->char_len;
                td->n_fields++;
            }
        }
        break;
    }

    case FND_IMPLICIT_NONE:
        if (I->current_scope) I->current_scope->implicit_none = 1;
        break;

    case FND_VARDECL:
    case FND_PARAMDECL: {
        OfortValue val;
        OfortVar *existing = find_var(I, n->name);
        if (existing && n->n_dims > 0) {
            int has_assumed_shape = 0;
            for (int i = 0; i < n->n_dims; i++) {
                if (n->dims[i] == 0) { has_assumed_shape = 1; break; }
            }
            if (has_assumed_shape) {
                existing->intent = n->intent;
                break;
            }
        }
        if (existing && n->intent != 0) {
            existing->intent = n->intent;
            break;
        }
        if (n->n_dims > 0 && !n->is_allocatable) {
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
            val = default_value(n->val_type, n->char_len);
        }

        /* If there's an initializer and it's an array, set elements */
        if (n->n_dims > 0 && !n->is_allocatable && n->n_children > 0 && n->children[0]) {
            OfortValue init = eval_node(I, n->children[0]);
            if (init.type == FVAL_ARRAY) {
                /* copy elements */
                int count = init.v.arr.len < val.v.arr.len ? init.v.arr.len : val.v.arr.len;
                for (int i = 0; i < count; i++) {
                    free_value(&val.v.arr.data[i]);
                    val.v.arr.data[i] = copy_value(init.v.arr.data[i]);
                }
            }
            free_value(&init);
        }

        OfortVar *v = declare_var(I, n->name, val);
        if (n->is_parameter || n->type == FND_PARAMDECL) v->is_parameter = 1;
        v->intent = n->intent;
        break;
    }

    case FND_ASSIGN: {
        OfortNode *lhs = n->children[0];
        OfortValue rhs = eval_node(I, n->children[1]);

        if (lhs->type == FND_IDENT) {
            /* Simple variable assignment */
            OfortVar *v = find_var(I, lhs->name);
            if (v && v->is_parameter) ofort_error(I, "Cannot assign to PARAMETER '%s'", lhs->name);
            set_var(I, lhs->name, rhs);
        } else if (lhs->type == FND_FUNC_CALL) {
            /* Array element assignment: arr(i) = val */
            OfortVar *var = find_var(I, lhs->name);
            if (!var) ofort_error(I, "Undefined variable '%s'", lhs->name);
            if (var->val.type != FVAL_ARRAY)
                ofort_error(I, "'%s' is not an array", lhs->name);

            int nargs = lhs->n_stmts;
            /* Check for slice assignment */
            int has_slice = 0;
            for (int i = 0; i < nargs; i++) {
                if (lhs->stmts[i]->type == FND_SLICE) { has_slice = 1; break; }
            }

            if (has_slice) {
                /* Slice assignment: arr(start:end) = rhs_array */
                OfortNode *slice = lhs->stmts[0];
                OfortValue sv = eval_node(I, slice->children[0]);
                int start = (int)val_to_int(sv) - 1;
                free_value(&sv);
                int end;
                if (slice->children[1]) {
                    OfortValue ev = eval_node(I, slice->children[1]);
                    end = (int)val_to_int(ev) - 1;
                    free_value(&ev);
                } else {
                    end = var->val.v.arr.dims[0] - 1;
                }
                if (rhs.type == FVAL_ARRAY) {
                    int ri = 0;
                    for (int idx = start; idx <= end && ri < rhs.v.arr.len; idx++, ri++) {
                        if (idx >= 0 && idx < var->val.v.arr.len) {
                            free_value(&var->val.v.arr.data[idx]);
                            var->val.v.arr.data[idx] = copy_value(rhs.v.arr.data[ri]);
                        }
                    }
                }
                free_value(&rhs);
            } else {
                /* Single element */
                OfortValue indices[7];
                for (int i = 0; i < nargs; i++) indices[i] = eval_node(I, lhs->stmts[i]);

                int index = 0;
                if (nargs == 1) {
                    index = (int)val_to_int(indices[0]) - 1;
                } else {
                    int stride = 1;
                    for (int i = 0; i < nargs; i++) {
                        index += ((int)val_to_int(indices[i]) - 1) * stride;
                        if (i < var->val.v.arr.n_dims)
                            stride *= var->val.v.arr.dims[i];
                    }
                }
                for (int i = 0; i < nargs; i++) free_value(&indices[i]);

                if (index < 0 || index >= var->val.v.arr.len)
                    ofort_error(I, "Array index out of bounds");
                free_value(&var->val.v.arr.data[index]);
                var->val.v.arr.data[index] = rhs;
            }
        } else if (lhs->type == FND_MEMBER) {
            /* Derived type member assignment: obj%field = val */
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
        long long iter = s;
        int max_iter = 1000000; /* safety limit */
        while (max_iter-- > 0) {
            if (st > 0 && iter > e) break;
            if (st < 0 && iter < e) break;
            set_var(I, n->name, make_integer(iter));
            exec_node(I, n->children[3]);
            if (I->returning || I->stopping) break;
            if (I->exiting) { I->exiting = 0; break; }
            if (I->cycling) { I->cycling = 0; }
            iter += st;
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
        int nvals = n->n_stmts;
        OfortValue *vals = (OfortValue *)calloc(nvals ? nvals : 1, sizeof(OfortValue));
        for (int i = 0; i < nvals; i++) vals[i] = eval_node(I, n->stmts[i]);
        format_output(I, n->format_str, vals, nvals);
        for (int i = 0; i < nvals; i++) free_value(&vals[i]);
        free(vals);
        break;
    }

    case FND_WRITE: {
        int nvals = n->n_stmts;
        OfortValue *vals = (OfortValue *)calloc(nvals ? nvals : 1, sizeof(OfortValue));
        for (int i = 0; i < nvals; i++) vals[i] = eval_node(I, n->stmts[i]);
        if (n->children[0]) {
            OfortValue uv = eval_node(I, n->children[0]);
            int unit = (int)val_to_int(uv);
            OfortUnitFile *entry = find_unit_file(I, unit);
            free_value(&uv);
            if (!entry) ofort_error(I, "Unit %d is not open", unit);
            write_values_to_file(I, entry->path, vals, nvals);
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
                read_values_from_file(I, entry->path, n);
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
                for (int i = 0; i < arr->v.arr.len; i++) {
                    free_value(&arr->v.arr.data[i]);
                    if (arr->v.arr.elem_type == FVAL_DOUBLE)
                        arr->v.arr.data[i] = make_double(random_unit());
                    else
                        arr->v.arr.data[i] = make_real(random_unit());
                }
            } else if (harvest->val.type == FVAL_REAL || harvest->val.type == FVAL_DOUBLE) {
                OfortValType t = harvest->val.type;
                free_value(&harvest->val);
                harvest->val = (t == FVAL_DOUBLE) ? make_double(random_unit()) : make_real(random_unit());
            } else {
                ofort_error(I, "RANDOM_NUMBER harvest must be REAL");
            }
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
        for (int i = 0; i < fn->n_params && i < nargs; i++) {
            OfortVar *pv = declare_var(I, fn->param_names[i], copy_value(args[i]));
            pv->intent = fn->param_intents[i];
        }

        exec_node(I, fn->children[0]);
        I->returning = 0;

        /* Handle INTENT(OUT/INOUT) — copy back */
        for (int i = 0; i < fn->n_params && i < nargs; i++) {
            if (fn->param_intents[i] != 1) {
                OfortVar *pv = find_var(I, fn->param_names[i]);
                if (pv && n->stmts[i]->type == FND_IDENT) {
                    free_value(&args[i]);
                    args[i] = copy_value(pv->val);
                }
            }
        }

        pop_scope(I);
        for (int i = 0; i < fn->n_params && i < nargs; i++) {
            if (n->stmts[i]->type == FND_IDENT && fn->param_intents[i] != 1) {
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
                        if (d->type == FND_VARDECL && d->intent != 0) {
                            /* Match parameter name */
                            char du[256];
                            str_upper(du, d->name, 256);
                            for (int k = 0; k < n->n_params; k++) {
                                char pu[256];
                                str_upper(pu, n->param_names[k], 256);
                                if (strcmp(du, pu) == 0) {
                                    n->param_intents[k] = d->intent;
                                    n->param_types[k] = d->val_type;
                                    break;
                                }
                            }
                        }
                    }
                } else if (s->type == FND_VARDECL && s->intent != 0) {
                    char du[256];
                    str_upper(du, s->name, 256);
                    for (int k = 0; k < n->n_params; k++) {
                        char pu[256];
                        str_upper(pu, n->param_names[k], 256);
                        if (strcmp(du, pu) == 0) {
                            n->param_intents[k] = s->intent;
                            n->param_types[k] = s->val_type;
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
        for (int i = 0; i < ndims; i++) {
            OfortValue dv = eval_node(I, n->stmts[i]);
            dims[i] = (int)val_to_int(dv);
            free_value(&dv);
        }
        free_value(&var->val);
        var->val = make_array(var->val.v.arr.elem_type ? var->val.v.arr.elem_type : FVAL_REAL, dims, ndims);
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
}

/* ══════════════════════════════════════════════
 *  INTRINSIC FUNCTIONS
 * ══════════════════════════════════════════════ */

static const char *intrinsic_names[] = {
    /* Math */
    "ABS", "SQRT", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "ATAN2",
    "EXP", "LOG", "LOG10", "MOD", "MAX", "MIN", "FLOOR", "CEILING", "NINT",
    "REAL", "INT", "DBLE", "CMPLX", "AIMAG", "CONJG", "SIGN", "KIND",
    /* String */
    "LEN", "LEN_TRIM", "TRIM", "ADJUSTL", "ADJUSTR", "INDEX",
    "CHAR", "ICHAR", "ACHAR", "IACHAR", "REPEAT",
    /* Array */
    "SIZE", "SHAPE", "SUM", "PRODUCT", "MAXVAL", "MINVAL",
    "DOT_PRODUCT", "MATMUL", "TRANSPOSE", "RESHAPE",
    "COUNT", "ANY", "ALL", "ALLOCATED", "LBOUND", "UBOUND",
    /* Type conversion */
    "FLOAT", "DFLOAT", "SNGL", "LOGICAL",
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

static OfortValue call_intrinsic(OfortInterpreter *I, const char *name, OfortValue *args, int nargs) {
    char upper[256];
    str_upper(upper, name, 256);

    if (nargs > 0 && args[0].type == FVAL_ARRAY && is_elemental_unary_intrinsic(upper)) {
        OfortValue result = copy_value(args[0]);
        result.v.arr.elem_type = elemental_result_type(upper, args[0].v.arr.elem_type);

        for (int i = 0; i < result.v.arr.len; i++) {
            OfortValue elem_arg = copy_value(args[0].v.arr.data[i]);
            OfortValue elem_result = call_intrinsic(I, name, &elem_arg, 1);
            free_value(&elem_arg);
            free_value(&result.v.arr.data[i]);
            result.v.arr.data[i] = elem_result;
        }

        return result;
    }

    /* === Math intrinsics === */
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
            case FVAL_INTEGER: return make_integer(4);
            case FVAL_REAL: return make_integer(4);
            case FVAL_DOUBLE: return make_integer(8);
            case FVAL_COMPLEX: return make_integer(8);
            case FVAL_LOGICAL: return make_integer(4);
            default: return make_integer(0);
        }
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
            strncpy(buf, args[0].v.s, OFORT_MAX_STRLEN - 1);
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
            strncpy(buf, args[0].v.s, OFORT_MAX_STRLEN - 1);
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
        if (nargs >= 2) {
            int dim = (int)val_to_int(args[1]);
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
    if (strcmp(upper, "SUM") == 0) {
        if (args[0].type != FVAL_ARRAY) return copy_value(args[0]);
        double sum = 0;
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
        if (nargs >= 2) return make_integer(1);
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
        if (nargs >= 2) {
            int dim = (int)val_to_int(args[1]);
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
    I->current_scope = I->global_scope;
    I->node_pool = NULL;
    I->node_pool_len = 0;
    I->node_pool_cap = 0;
    return I;
}

void ofort_destroy(OfortInterpreter *interp) {
    if (!interp) return;
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
    free(interp);
}

int ofort_execute(OfortInterpreter *interp, const char *source) {
    if (!interp || !source) return -1;
    interp->source = source;
    interp->has_error = 0;
    interp->returning = 0;
    interp->exiting = 0;
    interp->cycling = 0;
    interp->stopping = 0;
    interp->current_line = 0;

    if (setjmp(interp->err_jmp) != 0) {
        return -1;
    }

    /* Tokenize */
    tokenize(interp, source);
    interp->tok_pos = 0;

    /* Parse */
    interp->ast = parse_program(interp);

    /* First pass: register all top-level functions/subroutines/modules */
    if (interp->ast && interp->ast->type == FND_BLOCK) {
        for (int i = 0; i < interp->ast->n_stmts; i++) {
            OfortNode *s = interp->ast->stmts[i];
            if (!s) continue;
            if (s->type == FND_SUBROUTINE || s->type == FND_FUNCTION || s->type == FND_MODULE) {
                exec_node(interp, s);
            }
        }
    }

    /* Second pass: execute everything else */
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

const char *ofort_get_output(OfortInterpreter *interp) {
    return interp ? interp->output : "";
}

const char *ofort_get_error(OfortInterpreter *interp) {
    return interp ? interp->error : "";
}

void ofort_reset(OfortInterpreter *interp) {
    if (!interp) return;
    interp->output[0] = '\0';
    interp->out_len = 0;
    interp->error[0] = '\0';
    interp->has_error = 0;
    interp->returning = 0;
    interp->exiting = 0;
    interp->cycling = 0;
    interp->stopping = 0;
    interp->current_line = 0;
}
