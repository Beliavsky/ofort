/*
 * CodeBench Fortran Interpreter — a lightweight Fortran 90/95/2003 interpreter for iOS.
 * No JIT, no code generation, pure interpretation.
 * Supports: INTEGER, REAL, DOUBLE PRECISION, CHARACTER, LOGICAL, COMPLEX,
 *           arrays, derived types, modules, subroutines, functions,
 *           DO/IF/SELECT CASE, intrinsic functions, formatted I/O.
 */

#ifndef OFFLINAI_FORTRAN_H
#define OFFLINAI_FORTRAN_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Maximum limits */
#define OFORT_MAX_VARS      512
#define OFORT_MAX_FUNCS     128
#define OFORT_MAX_STACK     64
#define OFORT_MAX_OUTPUT    65536
#define OFORT_MAX_STRLEN    4096
#define OFORT_MAX_ARRAY     10000
#define OFORT_MAX_TOKENS    32768
#define OFORT_MAX_CHILDREN  16
#define OFORT_MAX_PARAMS    32
#define OFORT_MAX_MODULES   32
#define OFORT_MAX_FIELDS    32

/* ── Token types ────────────────────────────── */
typedef enum {
    FTOK_EOF = 0,
    /* literals */
    FTOK_INT_LIT, FTOK_REAL_LIT, FTOK_STRING_LIT,
    /* identifier */
    FTOK_IDENT,
    /* type keywords */
    FTOK_INTEGER, FTOK_REAL, FTOK_DOUBLE_PRECISION,
    FTOK_CHARACTER, FTOK_LOGICAL, FTOK_COMPLEX,
    /* structure keywords */
    FTOK_PROGRAM, FTOK_END, FTOK_SUBROUTINE, FTOK_FUNCTION,
    FTOK_MODULE, FTOK_USE, FTOK_CONTAINS, FTOK_TYPE,
    FTOK_IMPLICIT, FTOK_NONE,
    /* control keywords */
    FTOK_IF, FTOK_THEN, FTOK_ELSE, FTOK_ELSEIF,
    FTOK_DO, FTOK_WHILE, FTOK_SELECT, FTOK_CASE,
    FTOK_EXIT, FTOK_CYCLE, FTOK_RETURN, FTOK_STOP, FTOK_CALL,
    FTOK_DEFAULT,
    /* declaration keywords */
    FTOK_DIMENSION, FTOK_ALLOCATABLE, FTOK_ALLOCATE, FTOK_DEALLOCATE,
    FTOK_PARAMETER, FTOK_INTENT, FTOK_IN, FTOK_OUT, FTOK_INOUT,
    FTOK_RESULT, FTOK_SAVE, FTOK_DATA,
    /* I/O keywords */
    FTOK_PRINT, FTOK_WRITE, FTOK_READ,
    /* logical literal keywords */
    FTOK_TRUE, FTOK_FALSE,
    /* operators */
    FTOK_PLUS, FTOK_MINUS, FTOK_STAR, FTOK_SLASH, FTOK_POWER,
    FTOK_CONCAT,        /* // */
    FTOK_ASSIGN,        /* = */
    FTOK_EQ,            /* == or .EQ. */
    FTOK_NEQ,           /* /= or .NE. */
    FTOK_LT,            /* < or .LT. */
    FTOK_GT,            /* > or .GT. */
    FTOK_LE,            /* <= or .LE. */
    FTOK_GE,            /* >= or .GE. */
    FTOK_AND,           /* .AND. */
    FTOK_OR,            /* .OR. */
    FTOK_NOT,           /* .NOT. */
    FTOK_EQVOP,        /* .EQV. */
    FTOK_NEQVOP,       /* .NEQV. */
    /* punctuation */
    FTOK_LPAREN, FTOK_RPAREN,
    FTOK_LBRACKET, FTOK_RBRACKET,  /* (/ and /) for array constructors, or [ ] */
    FTOK_COMMA, FTOK_COLON, FTOK_DCOLON, /* :: */
    FTOK_PERCENT,       /* % for derived type member access */
    FTOK_NEWLINE,       /* statement separator */
    FTOK_SEMICOLON,     /* ; alternate statement separator */
} OfortTokenType;

typedef struct {
    OfortTokenType type;
    const char *start;
    int length;
    int line;
    double num_val;
    long long int_val;
    char str_val[OFORT_MAX_STRLEN];
} OfortToken;

/* ── Value types ─────────────────────────────── */
typedef enum {
    FVAL_INTEGER = 0,
    FVAL_REAL,
    FVAL_DOUBLE,
    FVAL_COMPLEX,
    FVAL_CHARACTER,
    FVAL_LOGICAL,
    FVAL_ARRAY,
    FVAL_DERIVED,
    FVAL_VOID,
} OfortValType;

typedef struct OfortValue {
    OfortValType type;
    union {
        long long       i;       /* INTEGER */
        double          r;       /* REAL / DOUBLE PRECISION */
        struct { double re, im; } cx; /* COMPLEX */
        char           *s;       /* CHARACTER */
        int             b;       /* LOGICAL: 1=.TRUE., 0=.FALSE. */
        struct {
            struct OfortValue *data;
            int len;
            int cap;
            OfortValType elem_type;
            int dims[7];    /* up to 7 dimensions (Fortran standard) */
            int n_dims;
            int allocated;  /* 1 if ALLOCATABLE and currently allocated */
        } arr;
        struct {
            struct OfortValue *fields;
            char (*field_names)[64];
            int n_fields;
            char type_name[64];
        } dt;
    } v;
} OfortValue;

/* ── AST node types ──────────────────────────── */
typedef enum {
    FND_PROGRAM, FND_BLOCK, FND_IMPLICIT_NONE,
    FND_VARDECL, FND_PARAMDECL,
    FND_SUBROUTINE, FND_FUNCTION, FND_MODULE,
    FND_TYPE_DEF,
    FND_IF, FND_DO_LOOP, FND_DO_WHILE, FND_SELECT_CASE, FND_CASE_BLOCK,
    FND_RETURN, FND_EXIT, FND_CYCLE, FND_STOP,
    FND_CALL, FND_PRINT, FND_WRITE, FND_READ_STMT,
    FND_ALLOCATE, FND_DEALLOCATE, FND_USE,
    FND_EXPR_STMT,
    /* expressions */
    FND_ASSIGN,
    FND_OR, FND_AND, FND_NOT,
    FND_EQV, FND_NEQV,
    FND_EQ, FND_NEQ, FND_LT, FND_GT, FND_LE, FND_GE,
    FND_ADD, FND_SUB, FND_MUL, FND_DIV, FND_POWER, FND_NEGATE,
    FND_CONCAT,
    FND_FUNC_CALL, FND_ARRAY_REF, FND_SLICE, FND_MEMBER,
    FND_INT_LIT, FND_REAL_LIT, FND_STRING_LIT,
    FND_LOGICAL_LIT, FND_COMPLEX_LIT,
    FND_IDENT,
    FND_ARRAY_CONSTRUCTOR,
} OfortNodeType;

typedef struct OfortNode {
    OfortNodeType type;
    /* data */
    double num_val;
    long long int_val;
    char name[256];
    char str_val[OFORT_MAX_STRLEN];
    OfortValType val_type;
    int bool_val;
    int char_len;           /* CHARACTER(LEN=n) */
    int intent;             /* 0=none, 1=IN, 2=OUT, 3=INOUT */
    int is_allocatable;
    int is_parameter;
    char result_name[256];  /* for FUNCTION ... RESULT(name) */
    char format_str[512];   /* for WRITE format */
    /* children */
    struct OfortNode *children[OFORT_MAX_CHILDREN];
    int n_children;
    /* for blocks / arg lists / case lists */
    struct OfortNode **stmts;
    int n_stmts;
    /* for function/subroutine parameters */
    char param_names[OFORT_MAX_PARAMS][256];
    OfortValType param_types[OFORT_MAX_PARAMS];
    int param_intents[OFORT_MAX_PARAMS];
    int n_params;
    /* array dimensions in declarations */
    int dims[7];
    int n_dims;
    /* source location */
    int line;
} OfortNode;

/* ── Public API ──────────────────────────────── */

typedef struct OfortInterpreter OfortInterpreter;

/* Create/destroy */
OfortInterpreter *ofort_create(void);
void ofort_destroy(OfortInterpreter *interp);

/* Execute Fortran source code. Returns 0 on success, -1 on error. */
int ofort_execute(OfortInterpreter *interp, const char *source);

/* Get output (stdout from PRINT/WRITE etc.) */
const char *ofort_get_output(OfortInterpreter *interp);

/* Get error message (if ofort_execute returned -1) */
const char *ofort_get_error(OfortInterpreter *interp);

/* Reset for next execution (clears output/errors but keeps state) */
void ofort_reset(OfortInterpreter *interp);

#ifdef __cplusplus
}
#endif

#endif /* OFFLINAI_FORTRAN_H */
