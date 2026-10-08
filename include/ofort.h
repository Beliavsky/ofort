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

#define OFORT_VERSION "0.1.0"
#ifndef OFORT_BUILD_FLAGS
#define OFORT_BUILD_FLAGS "-O2"
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Maximum limits */
#define OFORT_MAX_VARS      4096
#define OFORT_MAX_SAVED_VARS 256
#define OFORT_MAX_MODULE_VARS 512
#define OFORT_MAX_FUNCS     128
#define OFORT_MAX_STACK     64
#define OFORT_MAX_OUTPUT    65536
#define OFORT_MAX_STRLEN    4096
#define OFORT_TOKEN_STRLEN  1024
#define OFORT_MAX_ARRAY     10000
#define OFORT_MAX_TOKENS    32768
#define OFORT_MAX_CHILDREN  16
#define OFORT_MAX_PARAMS    256
#ifndef OFORT_MAX_MODULES
#define OFORT_MAX_MODULES   256
#endif
#define OFORT_MAX_FIELDS    32

typedef enum {
    OFORT_STD_LEGACY = 0,
    OFORT_STD_F2023 = 2023
} OfortStandardMode;

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
    FTOK_EXIT, FTOK_CYCLE, FTOK_RETURN, FTOK_STOP, FTOK_CALL, FTOK_ENTRY,
    FTOK_DEFAULT,
    /* declaration keywords */
    FTOK_DIMENSION, FTOK_ALLOCATABLE, FTOK_ALLOCATE, FTOK_DEALLOCATE,
    FTOK_PARAMETER, FTOK_INTENT, FTOK_IN, FTOK_OUT, FTOK_INOUT,
    FTOK_RESULT, FTOK_SAVE, FTOK_DATA,
    /* I/O keywords */
    FTOK_PRINT, FTOK_WRITE, FTOK_READ, FTOK_OPEN, FTOK_CLOSE, FTOK_REWIND, FTOK_BACKSPACE, FTOK_ENDFILE, FTOK_WAIT, FTOK_INQUIRE,
    /* logical literal keywords */
    FTOK_TRUE, FTOK_FALSE,
    /* operators */
    FTOK_PLUS, FTOK_MINUS, FTOK_STAR, FTOK_SLASH, FTOK_POWER,
    FTOK_CONCAT,        /* // */
    FTOK_ASSIGN,        /* = */
    FTOK_POINTER_ASSIGN,/* => */
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
    FTOK_USER_OP,      /* user-defined .NAME. operator */
    /* punctuation */
    FTOK_LPAREN, FTOK_RPAREN,
    FTOK_LBRACKET, FTOK_RBRACKET,  /* (/ and /) for array constructors, or [ ] */
    FTOK_COMMA, FTOK_COLON, FTOK_DCOLON, /* :: */
    FTOK_AT,            /* @ in Fortran 2023 multiple subscripts */
    FTOK_QUESTION,      /* ? in Fortran 2023 conditional expressions */
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
    int kind;
    char str_val[OFORT_TOKEN_STRLEN];
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
    int kind;
    int is_pointer_ref;
    char pointer_target[256];
    int pointer_has_slice;
    int pointer_slice_start;
    int pointer_slice_end;
    int pointer_slice_stride;
    int pointer_section_rank;
    int pointer_section_lower[7];
    int pointer_section_start[7];
    int pointer_section_end[7];
    int pointer_section_stride[7];
    int pointer_section_dims[7];
    char int_repr[64];  /* Optional exact decimal text for INTEGER values outside long long. */
    union {
        long long       i;       /* INTEGER */
        __int128        i128;    /* INTEGER(16) */
        double          r;       /* REAL / DOUBLE PRECISION */
        struct { double re, im; } cx; /* COMPLEX */
        char           *s;       /* CHARACTER */
        int             b;       /* LOGICAL: 1=.TRUE., 0=.FALSE. */
        struct {
            struct OfortValue *data;
            double *real_data;
            long long *int_data;
            int len;
            int cap;
            OfortValType elem_type;
            char elem_type_name[64];
            int dims[7];    /* up to 7 dimensions (Fortran standard) */
            int lower_bounds[7];
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
    FND_PROGRAM, FND_BLOCK, FND_BLOCK_CONSTRUCT, FND_ASSOCIATE, FND_IMPLICIT_NONE,
    FND_VARDECL, FND_PARAMDECL,
    FND_SUBROUTINE, FND_FUNCTION, FND_MODULE, FND_BLOCK_DATA,
    FND_TYPE_DEF,
    FND_ENUM,
    FND_IF, FND_DO_LOOP, FND_DO_WHILE, FND_DO_FOREVER, FND_DO_CONCURRENT, FND_FORALL, FND_WHERE, FND_SELECT_CASE, FND_SELECT_RANK, FND_CASE_BLOCK,
    FND_RETURN, FND_EXIT, FND_CYCLE, FND_STOP, FND_GOTO, FND_CONTINUE,
    FND_CALL, FND_PRINT, FND_WRITE, FND_READ_STMT, FND_OPEN, FND_CLOSE, FND_REWIND, FND_BACKSPACE, FND_ENDFILE, FND_WAIT, FND_INQUIRE,
    FND_NAMELIST,
    FND_ALLOCATE, FND_DEALLOCATE, FND_USE, FND_IMPORT, FND_ACCESS, FND_ATTR_STMT, FND_INTERFACE,
    FND_EXPR_STMT,
    FND_DATA, FND_EQUIVALENCE,
    FND_FORMAT,
    FND_STMT_FUNCTION,
    /* expressions */
    FND_ASSIGN,
    FND_POINTER_ASSIGN,
    FND_OR, FND_AND, FND_NOT,
    FND_EQV, FND_NEQV,
    FND_EQ, FND_NEQ, FND_LT, FND_GT, FND_LE, FND_GE,
    FND_ADD, FND_SUB, FND_MUL, FND_DIV, FND_POWER, FND_NEGATE,
    FND_CONCAT,
    FND_CONDITIONAL,
    FND_MULTIPLE_SUBSCRIPT,
    FND_FUNC_CALL, FND_ARRAY_REF, FND_SLICE, FND_MEMBER,
    FND_INT_LIT, FND_REAL_LIT, FND_STRING_LIT,
    FND_LOGICAL_LIT, FND_COMPLEX_LIT,
    FND_IDENT,
    FND_ARRAY_CONSTRUCTOR,
    FND_IMPLIED_DO,
} OfortNodeType;

typedef struct OfortNode {
    OfortNodeType type;
    /* data */
    double num_val;
    long long int_val;
    int kind;
    char name[256];
    char str_val[OFORT_MAX_STRLEN];
    OfortValType val_type;
    int bool_val;
    char implicit_types[26];
    int implicit_char_lens[26];
    char implicit_type_names[26][64];
    int char_len;           /* CHARACTER(LEN=n) */
    int intent;             /* 0=none, 1=IN, 2=OUT, 3=INOUT */
    int is_allocatable;
    int is_pointer;
    int is_target;
    int is_protected;
    int is_save;
    int is_implicit_save;
    int is_parameter;
    int is_optional;
    int is_value;
    int procedure_nopass;
    char procedure_pass_name[64];
    int is_elemental;
    int is_pure;
    int access_attr;        /* 0=none, 1=PUBLIC, 2=PRIVATE */
    int no_advance;         /* WRITE(..., ADVANCE='NO') */
    char result_name[256];  /* for FUNCTION ... RESULT(name) */
    int has_explicit_result_type;
    char format_str[512];   /* for WRITE format */
    char parent_type_name[64]; /* for TYPE, EXTENDS(parent) */
    /* children */
    struct OfortNode *children[OFORT_MAX_CHILDREN];
    int n_children;
    /* for blocks / arg lists / case lists */
    struct OfortNode **stmts;
    int n_stmts;
    /* for function/subroutine parameters */
    char (*param_names)[256];
    char (*binding_proc_names)[256];
    OfortValType *param_types;
    int *param_kinds;
    char (*param_type_names)[64];
    int *param_intents;
    int *param_optional;
    int *param_values;
    int *param_pointers;
    int *param_allocatables;
    int *param_n_dims;
    int n_params;
    char (*type_param_names)[64];
    int n_type_params;
    /* array dimensions in declarations */
    int dims[7];
    int lower_bounds[7];
    int has_lower_bound[7];
    struct OfortNode *lower_bound_exprs[7];
    int n_dims;
    struct OfortNode *char_len_expr;
    struct OfortNode *kind_expr;
    struct OfortNode **type_param_exprs;
    int n_type_param_exprs;
    void *fast_cache[8];
    /* source location */
    int line;
} OfortNode;

/* ── Public API ──────────────────────────────── */

typedef struct OfortInterpreter OfortInterpreter;

typedef struct {
    double lex;
    double parse;
    double register_time;
    double execute;
    double total;
} OfortTiming;

typedef struct {
    int line;
    int count;
    double seconds;
} OfortLineProfileEntry;

typedef struct {
    char name[256];
    char module_name[256];
    int is_function;
    int count;
    double seconds;
} OfortProcedureProfileEntry;

typedef struct {
    char status[16];
    char name[256];
    char module_name[256];
    char kind[32];
    int line;
} OfortUnusedProcedureEntry;

/* Create/destroy */
OfortInterpreter *ofort_create(void);
void ofort_destroy(OfortInterpreter *interp);

/* Execute Fortran source code. Returns 0 on success, -1 on error. */
int ofort_execute(OfortInterpreter *interp, const char *source);

/* REPL-only: infer a missing scalar target for one top-level assignment. */
int ofort_execute_auto_declare(OfortInterpreter *interp, const char *source);
const char *ofort_get_auto_declaration(OfortInterpreter *interp);

/* Check syntax by lexing/parsing only. Returns 0 on success, -1 on error. */
int ofort_check(OfortInterpreter *interp, const char *source);

/* Analyze registered user procedures and copy records for procedures not reachable from the main program. */
int ofort_analyze_unused_procs(OfortInterpreter *interp, const char *source,
                               OfortUnusedProcedureEntry *entries,
                               int max_entries, int *n_entries);

/* If enabled, bare expression statements write their value to output. */
void ofort_set_print_expr_statements(OfortInterpreter *interp, int enabled);

/* If enabled, normal program output is suppressed. Bare expression output remains enabled. */
void ofort_set_suppress_output(OfortInterpreter *interp, int enabled);

/* Enable or disable historical Fortran implicit typing for undeclared names. Enabled by default. */
void ofort_set_implicit_typing(OfortInterpreter *interp, int enabled);

/* If disabled, warnings are suppressed. Errors are unaffected. */
void ofort_set_warnings_enabled(OfortInterpreter *interp, int enabled);

/* Warn about beyond-end array element actuals accepted as empty sequences. Off by default. */
void ofort_set_warn_empty_sequence(OfortInterpreter *interp, int enabled);

/* If disabled, suppress warnings when user names shadow intrinsic procedures. */
void ofort_set_warn_intrinsic_shadow(OfortInterpreter *interp, int enabled);
void ofort_set_warn_function_side_effects(OfortInterpreter *interp, int enabled);

/* If enabled, use safe interpreter fast paths. */
void ofort_set_fast_mode(OfortInterpreter *interp, int enabled);

/* If disabled, suppress specialized pattern/program fast paths while keeping general fast mode. */
void ofort_set_specialized_fast_paths(OfortInterpreter *interp, int enabled);

/* If enabled, accumulate elapsed execution time by source line. */
void ofort_set_line_profile_enabled(OfortInterpreter *interp, int enabled);

/* Enable or disable procedure-level execution profiling. */
void ofort_set_procedure_profile_enabled(OfortInterpreter *interp, int enabled);

/* If enabled, assignment statements emit trace diagnostics. */
void ofort_set_trace_assign(OfortInterpreter *interp, int enabled);

/* If enabled, PRINT/WRITE output to unit 6 is emitted as it is produced. */
void ofort_set_live_stdout(OfortInterpreter *interp, int enabled);

/* If enabled, reading a declared but never assigned scalar is an error. */
void ofort_set_strict_uninitialized(OfortInterpreter *interp, int enabled);

/* Debug initializers for otherwise uninitialized INTEGER, REAL/DOUBLE, and CHARACTER declarations. */
void ofort_set_init_integer(OfortInterpreter *interp, int enabled, long long value);
void ofort_set_init_real(OfortInterpreter *interp, int enabled, double value);
void ofort_set_init_character(OfortInterpreter *interp, int enabled, const char *value);

/* Set parser standard mode. Default is OFORT_STD_LEGACY. */
void ofort_set_standard_mode(OfortInterpreter *interp, OfortStandardMode mode);

/* Set command-line arguments visible to COMMAND_ARGUMENT_COUNT/GET_COMMAND_ARGUMENT. */
void ofort_set_command_args(OfortInterpreter *interp, int argc, const char *const *argv);

/*
 * Register a native subroutine implemented by a shared library.
 * ABI "r8arr_r8arr" means an interpreted call:
 *   subroutine name(x, y)
 *     real(8) :: x(:), y(:)
 * where the C/Fortran bind(C) symbol takes
 * (int *nx, double *x, int *ny, double *y).
 *
 * ABI "r8arr_r8" means an interpreted function call:
 *   y = name(x)
 * where the C/Fortran bind(C) symbol takes
 * (int *nx, double *x, double *y).
 *
 * ABI "r8arr_r8arr_r8" means an interpreted function call:
 *   z = name(x, y)
 * where the C/Fortran bind(C) symbol takes
 * (int *nx, double *x, int *ny, double *y, double *z).
 *
 * ABI "r8mat_r8mat" means an interpreted call:
 *   subroutine name(x, y)
 *     real(8) :: x(:,:), y(:,:)
 * where the C/Fortran bind(C) symbol takes
 * (int *nx1, int *nx2, double *x, int *ny1, int *ny2, double *y).
 *
 * ABI "i4_r8arr" means an interpreted function call:
 *   x = name(n)
 * where n is an integer and x is a returned real(8) rank-1 array of length n.
 * The C/Fortran bind(C) symbol takes
 * (int *n, int *ny, double *y).
 */
int ofort_add_native_subroutine(OfortInterpreter *interp, const char *name,
                                const char *library_path, const char *symbol,
                                const char *abi);

/* Write visible variable values to buf. If names is NULL or n_names is 0, lists all variables. */
int ofort_dump_variables(OfortInterpreter *interp, const char *const *names,
                         int n_names, char *buf, size_t buf_size);

/* Write declaration-style visible variable info to buf. If names is NULL or n_names is 0, lists all variables. */
int ofort_dump_variable_info(OfortInterpreter *interp, const char *const *names,
                             int n_names, char *buf, size_t buf_size);

/* Bounded visible-variable previews: at most six array elements, with unset
   elements identified from initialization metadata without evaluating them. */
int ofort_dump_variable_previews(OfortInterpreter *interp, char *buf, size_t buf_size);

/* Write array shapes to buf. If names is NULL or n_names is 0, lists all visible arrays. */
int ofort_dump_variable_shapes(OfortInterpreter *interp, const char *const *names,
                               int n_names, char *buf, size_t buf_size);

/* Write array sizes to buf. If names is NULL or n_names is 0, lists all visible arrays. */
int ofort_dump_variable_sizes(OfortInterpreter *interp, const char *const *names,
                              int n_names, char *buf, size_t buf_size);

/* Write grouped numeric array statistics to buf. If names is NULL or n_names is 0, lists all visible numeric arrays. */
int ofort_dump_variable_stats(OfortInterpreter *interp, const char *const *names,
                              int n_names, char *buf, size_t buf_size);

/* Write replayable declarations and assignments for visible simple variables. */
int ofort_dump_state_initializers(OfortInterpreter *interp, char *buf, size_t buf_size);
int ofort_dump_state_initializers_binary(OfortInterpreter *interp, char *buf, size_t buf_size,
                                         const char *binary_dir, int binary_array_threshold);

/* Get output (stdout from PRINT/WRITE etc.) */
const char *ofort_get_output(OfortInterpreter *interp);

/* Get error message (if ofort_execute returned -1) */
const char *ofort_get_error(OfortInterpreter *interp);

/* Get warning messages from the last execution, if any. */
const char *ofort_get_warnings(OfortInterpreter *interp);

/* Get timing data from the last execution or check. */
int ofort_get_timing(OfortInterpreter *interp, OfortTiming *timing);

/* Copy nonzero line-profile entries into entries and set n_entries to the total available. */
int ofort_get_line_profile(OfortInterpreter *interp, OfortLineProfileEntry *entries,
                           int max_entries, int *n_entries);

/* Copy nonzero procedure-profile entries into entries and set n_entries to the total available. */
int ofort_get_procedure_profile(OfortInterpreter *interp, OfortProcedureProfileEntry *entries,
                                int max_entries, int *n_entries);

/* Call a registered interpreted function as REAL/DOUBLE PRECISION f(REAL). */
int ofort_call_real1(OfortInterpreter *interp, const char *name, double x, double *result);

/* Reset for next execution (clears output/errors but keeps state) */
void ofort_reset(OfortInterpreter *interp);

#ifdef __cplusplus
}
#endif

#endif /* OFFLINAI_FORTRAN_H */
