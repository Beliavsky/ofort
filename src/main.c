#include "ofort.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>

#ifdef _WIN32
#include <io.h>
#include <process.h>
#define ISATTY(fd) _isatty(fd)
#define FILENO(fp) _fileno(fp)
#define GETPID() _getpid()
#else
#include <unistd.h>
#define ISATTY(fd) isatty(fd)
#define FILENO(fp) fileno(fp)
#define GETPID() getpid()
#endif

static void normalize_newlines(char *source);
static char *maybe_wrap_loose_source(char *source);
static char *read_file(const char *path);
static const char *skip_space(const char *line);
static int starts_with_word_nocase(const char *line, const char *word);
static int identifier_char(int c);
static int line_is_terminal_end(const char *start, const char *end);

static int append_text(char **buf, size_t *len, size_t *cap, const char *text) {
    size_t n = strlen(text);

    if (*len + n + 1 > *cap) {
        size_t new_cap = *cap ? *cap : 8192;
        char *new_buf;

        while (*len + n + 1 > new_cap) {
            new_cap *= 2;
        }

        new_buf = (char *)realloc(*buf, new_cap);
        if (!new_buf) {
            fprintf(stderr, "out of memory\n");
            return 0;
        }

        *buf = new_buf;
        *cap = new_cap;
    }

    memcpy(*buf + *len, text, n);
    *len += n;
    (*buf)[*len] = '\0';
    return 1;
}

static char *read_stream(FILE *fp, const char *name) {
    size_t cap = 8192;
    size_t len = 0;
    char *buf = (char *)malloc(cap);

    if (!buf) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }

    for (;;) {
        size_t n;

        if (len + 4096 + 1 > cap) {
            size_t new_cap = cap * 2;
            char *new_buf = (char *)realloc(buf, new_cap);
            if (!new_buf) {
                free(buf);
                fprintf(stderr, "out of memory while reading %s\n", name);
                return NULL;
            }
            buf = new_buf;
            cap = new_cap;
        }

        n = fread(buf + len, 1, 4096, fp);
        len += n;

        if (n < 4096) {
            if (ferror(fp)) {
                free(buf);
                fprintf(stderr, "failed to read %s\n", name);
                return NULL;
            }
            break;
        }
    }

    buf[len] = '\0';
    return buf;
}

static char *copy_string(const char *text) {
    size_t len = strlen(text);
    char *copy = (char *)malloc(len + 1);

    if (!copy) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }

    memcpy(copy, text, len + 1);
    return copy;
}

static int is_command(const char *line, const char *command) {
    size_t n = strlen(command);

    return strncmp(line, command, n) == 0 &&
           (line[n] == '\0' || line[n] == '\n' || line[n] == '\r');
}

static void list_source(const char *source) {
    const char *line = source;
    int line_no = 1;

    while (*line) {
        const char *end = strchr(line, '\n');

        if (end) {
            printf("%4d  %.*s\n", line_no, (int)(end - line), line);
            line = end + 1;
        } else {
            printf("%4d  %s\n", line_no, line);
            break;
        }
        line_no++;
    }
}

static int file_exists(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        return 0;
    }
    fclose(fp);
    return 1;
}

static int append_effective_source(char **out, size_t *len, size_t *cap,
                                   const char *source, const char *footer) {
    if (source && !append_text(out, len, cap, source)) {
        return 0;
    }
    if (footer && footer[0] != '\0') {
        if (*len > 0 && (*out)[*len - 1] != '\n') {
            if (!append_text(out, len, cap, "\n")) {
                return 0;
            }
        }
        if (!append_text(out, len, cap, footer)) {
            return 0;
        }
        if (*len > 0 && (*out)[*len - 1] != '\n') {
            if (!append_text(out, len, cap, "\n")) {
                return 0;
            }
        }
    }
    return 1;
}

static char *make_effective_source(const char *source, const char *footer) {
    char *combined = NULL;
    size_t len = 0;
    size_t cap = 0;

    if (!append_effective_source(&combined, &len, &cap, source, footer)) {
        free(combined);
        return NULL;
    }
    if (!combined) {
        combined = copy_string("");
    }
    return combined;
}

static int source_has_terminal_end(const char *source) {
    const char *end;
    const char *line_start;

    if (!source) {
        return 0;
    }

    end = source + strlen(source);
    while (end > source && isspace((unsigned char)end[-1])) {
        end--;
    }
    if (end == source) {
        return 0;
    }

    line_start = end;
    while (line_start > source && line_start[-1] != '\n') {
        line_start--;
    }

    return line_is_terminal_end(line_start, end);
}

static int find_program_name(const char *source, char *name, size_t name_size) {
    const char *line = source;

    if (name_size == 0) {
        return 0;
    }
    name[0] = '\0';

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        const char *p;
        size_t len = end ? (size_t)(end - line) : strlen(line);
        size_t n = 0;

        if (len >= sizeof(local)) {
            len = sizeof(local) - 1;
        }
        memcpy(local, line, len);
        local[len] = '\0';
        p = skip_space(local);
        if (*p != '\0' && *p != '!') {
            if (!starts_with_word_nocase(p, "program")) {
                return 0;
            }
            p += 7;
            p = skip_space(p);
            if (!(isalpha((unsigned char)*p) || *p == '_')) {
                return 0;
            }
            while (identifier_char(*p) && n + 1 < name_size) {
                name[n++] = *p++;
            }
            name[n] = '\0';
            return n > 0;
        }
        line = end ? end + 1 : NULL;
    }

    return 0;
}

static char *make_save_source(const char *source, const char *footer) {
    char *effective = make_effective_source(source, footer);
    char program_name[256];
    size_t len;
    size_t cap;

    if (!effective) {
        return NULL;
    }
    if (source_has_terminal_end(effective)) {
        return effective;
    }

    len = strlen(effective);
    cap = len + 1;
    if (len > 0 && effective[len - 1] != '\n') {
        if (!append_text(&effective, &len, &cap, "\n")) {
            free(effective);
            return NULL;
        }
    }
    if (find_program_name(effective, program_name, sizeof(program_name))) {
        if (!append_text(&effective, &len, &cap, "end program ")) {
            free(effective);
            return NULL;
        }
        if (!append_text(&effective, &len, &cap, program_name)) {
            free(effective);
            return NULL;
        }
        if (!append_text(&effective, &len, &cap, "\n")) {
            free(effective);
            return NULL;
        }
    } else if (!append_text(&effective, &len, &cap, "end\n")) {
        free(effective);
        return NULL;
    }
    return effective;
}

static int save_interactive_source(const char *source, const char *footer) {
    char path[64];
    char *effective;
    FILE *fp;
    int i;

    if (!source || source[0] == '\0') {
        return 0;
    }

    strcpy(path, "main.f90");
    for (i = 1; file_exists(path); i++) {
        snprintf(path, sizeof(path), "main%d.f90", i);
    }

    fp = fopen(path, "wb");
    if (!fp) {
        fprintf(stderr, "failed to save %s\n", path);
        return 1;
    }
    effective = make_save_source(source, footer);
    if (!effective) {
        fclose(fp);
        fprintf(stderr, "out of memory\n");
        return 1;
    }
    fputs(effective, fp);
    free(effective);
    fclose(fp);
    printf("Saved %s\n", path);
    return 0;
}

static const char *skip_space(const char *line) {
    while (*line == ' ' || *line == '\t') {
        line++;
    }
    return line;
}

static int starts_with_word_nocase(const char *line, const char *word) {
    size_t i;

    line = skip_space(line);
    for (i = 0; word[i]; i++) {
        if (tolower((unsigned char)line[i]) != tolower((unsigned char)word[i])) {
            return 0;
        }
    }

    return line[i] == '\0' || line[i] == '\r' || line[i] == '\n' ||
           !(isalnum((unsigned char)line[i]) || line[i] == '_');
}

static int names_match(const char *start, size_t len, const char *name) {
    size_t i;

    if (strlen(name) != len) {
        return 0;
    }
    for (i = 0; i < len; i++) {
        if (tolower((unsigned char)start[i]) != tolower((unsigned char)name[i])) {
            return 0;
        }
    }
    return 1;
}

static int line_is_name_only(const char *line, const char *name) {
    const char *p = skip_space(line);
    size_t len = strlen(name);

    if (!names_match(p, len, name)) {
        return 0;
    }
    p += len;
    while (*p == ' ' || *p == '\t') {
        p++;
    }
    return *p == '\0' || *p == '\r' || *p == '\n';
}

static int contains_assignment(const char *line) {
    const char *p = line;

    while (*p) {
        if (*p == '=') {
            return 1;
        }
        p++;
    }
    return 0;
}

static int identifier_char(int c) {
    return isalnum((unsigned char)c) || c == '_';
}

typedef enum {
    REPL_TYPE_UNKNOWN = 0,
    REPL_TYPE_INTEGER,
    REPL_TYPE_REAL,
    REPL_TYPE_DOUBLE,
    REPL_TYPE_COMPLEX,
    REPL_TYPE_CHARACTER,
    REPL_TYPE_LOGICAL
} ReplType;

static const char *repl_type_name(ReplType type) {
    switch (type) {
        case REPL_TYPE_INTEGER: return "INTEGER";
        case REPL_TYPE_REAL: return "REAL";
        case REPL_TYPE_DOUBLE: return "DOUBLE PRECISION";
        case REPL_TYPE_COMPLEX: return "COMPLEX";
        case REPL_TYPE_CHARACTER: return "CHARACTER";
        case REPL_TYPE_LOGICAL: return "LOGICAL";
        default: return "UNKNOWN";
    }
}

static int repl_type_is_numeric(ReplType type) {
    return type == REPL_TYPE_INTEGER || type == REPL_TYPE_REAL ||
           type == REPL_TYPE_DOUBLE || type == REPL_TYPE_COMPLEX;
}

static ReplType declaration_type(const char *line) {
    if (starts_with_word_nocase(line, "integer")) return REPL_TYPE_INTEGER;
    if (starts_with_word_nocase(line, "real")) return REPL_TYPE_REAL;
    if (starts_with_word_nocase(line, "double")) return REPL_TYPE_DOUBLE;
    if (starts_with_word_nocase(line, "complex")) return REPL_TYPE_COMPLEX;
    if (starts_with_word_nocase(line, "character")) return REPL_TYPE_CHARACTER;
    if (starts_with_word_nocase(line, "logical")) return REPL_TYPE_LOGICAL;
    return REPL_TYPE_UNKNOWN;
}

static int is_repl_declaration_line(const char *line) {
    return declaration_type(line) != REPL_TYPE_UNKNOWN ||
           starts_with_word_nocase(line, "implicit");
}

static int is_blank_or_comment_line(const char *line) {
    const char *p = skip_space(line);
    return *p == '\0' || *p == '\r' || *p == '\n' || *p == '!';
}

static int is_buffer_declaration_line(const char *line) {
    return is_blank_or_comment_line(line) || is_repl_declaration_line(line);
}

static int insert_text_at(char **buf, size_t *len, size_t *cap, size_t pos, const char *text) {
    size_t n = strlen(text);

    if (pos > *len) {
        pos = *len;
    }
    if (*len + n + 1 > *cap) {
        size_t new_cap = *cap ? *cap : 8192;
        char *new_buf;
        while (*len + n + 1 > new_cap) {
            new_cap *= 2;
        }
        new_buf = (char *)realloc(*buf, new_cap);
        if (!new_buf) {
            fprintf(stderr, "out of memory\n");
            return 0;
        }
        *buf = new_buf;
        *cap = new_cap;
    }
    memmove(*buf + pos + n, *buf + pos, *len - pos + 1);
    memcpy(*buf + pos, text, n);
    *len += n;
    return 1;
}

static size_t declaration_insert_position(const char *source) {
    const char *line = source;
    size_t pos = 0;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t line_len = end ? (size_t)(end - line + 1) : strlen(line);
        size_t text_len = end ? (size_t)(end - line) : strlen(line);
        if (text_len >= sizeof(local)) {
            text_len = sizeof(local) - 1;
        }
        memcpy(local, line, text_len);
        local[text_len] = '\0';
        if (!is_buffer_declaration_line(local)) {
            break;
        }
        pos += line_len;
        line = end ? end + 1 : NULL;
    }

    return pos;
}

static int add_repl_line_to_buffer(char **buf, size_t *len, size_t *cap, const char *line) {
    if (is_repl_declaration_line(line)) {
        size_t pos = declaration_insert_position(*buf ? *buf : "");
        return insert_text_at(buf, len, cap, pos, line);
    }
    return append_text(buf, len, cap, line);
}

static int declaration_line_has_name(const char *line, const char *name) {
    const char *p = strstr(line, "::");
    p = p ? p + 2 : line;

    while (*p) {
        while (*p && !isalpha((unsigned char)*p) && *p != '_') {
            p++;
        }
        if (!*p) {
            break;
        }
        const char *start = p;
        while (identifier_char(*p)) {
            p++;
        }
        if (names_match(start, (size_t)(p - start), name)) {
            return 1;
        }
        while (*p == ' ' || *p == '\t') {
            p++;
        }
        if (*p == '(') {
            int depth = 1;
            p++;
            while (*p && depth > 0) {
                if (*p == '(') depth++;
                else if (*p == ')') depth--;
                p++;
            }
        }
    }

    return 0;
}

static ReplType source_declared_type(const char *source, const char *name) {
    const char *line = source;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        ReplType type;

        if (len >= sizeof(local)) {
            len = sizeof(local) - 1;
        }
        memcpy(local, line, len);
        local[len] = '\0';

        type = declaration_type(local);
        if (type != REPL_TYPE_UNKNOWN && declaration_line_has_name(local, name)) {
            return type;
        }
        line = end ? end + 1 : NULL;
    }

    return REPL_TYPE_UNKNOWN;
}

static ReplType literal_rhs_type(const char *rhs) {
    const char *p = skip_space(rhs);

    if (*p == '"' || *p == '\'') {
        return REPL_TYPE_CHARACTER;
    }
    if (starts_with_word_nocase(p, ".true.") || starts_with_word_nocase(p, ".false.")) {
        return REPL_TYPE_LOGICAL;
    }
    if (*p == '+' || *p == '-') {
        p++;
    }
    if (isdigit((unsigned char)*p) || *p == '.') {
        while (*p && !isspace((unsigned char)*p) && *p != ',') {
            if (*p == '.' || *p == 'e' || *p == 'E') return REPL_TYPE_REAL;
            if (*p == 'd' || *p == 'D') return REPL_TYPE_DOUBLE;
            p++;
        }
        return REPL_TYPE_INTEGER;
    }

    return REPL_TYPE_UNKNOWN;
}

static int extract_simple_assignment(const char *line, char *name, size_t name_size,
                                     const char **rhs_out) {
    const char *p = skip_space(line);
    const char *start;
    const char *eq;
    size_t len;

    if (!(isalpha((unsigned char)*p) || *p == '_')) {
        return 0;
    }
    start = p;
    while (identifier_char(*p)) {
        p++;
    }
    len = (size_t)(p - start);
    if (len >= name_size) {
        len = name_size - 1;
    }
    memcpy(name, start, len);
    name[len] = '\0';

    while (*p == ' ' || *p == '\t') {
        p++;
    }
    if (*p != '=') {
        return 0;
    }
    eq = p;
    if ((eq > line && (eq[-1] == '<' || eq[-1] == '>' || eq[-1] == '/' || eq[-1] == '=')) ||
        eq[1] == '=') {
        return 0;
    }
    *rhs_out = eq + 1;
    return 1;
}

static int assignment_allowed_for_declared_type(ReplType lhs, ReplType rhs) {
    if (lhs == REPL_TYPE_UNKNOWN || rhs == REPL_TYPE_UNKNOWN) {
        return 1;
    }
    if (lhs == rhs) {
        return 1;
    }
    return repl_type_is_numeric(lhs) && repl_type_is_numeric(rhs);
}

static int validate_repl_line_before_append(const char *source, const char *line) {
    char name[256];
    const char *rhs;
    ReplType lhs_type;
    ReplType rhs_type;

    if (!extract_simple_assignment(line, name, sizeof(name), &rhs)) {
        return 1;
    }

    lhs_type = source_declared_type(source ? source : "", name);
    rhs_type = literal_rhs_type(rhs);
    if (!assignment_allowed_for_declared_type(lhs_type, rhs_type)) {
        fprintf(stderr, "Cannot assign %s to %s variable '%s'\n",
                repl_type_name(rhs_type), repl_type_name(lhs_type), name);
        fprintf(stderr, "line: %s", line);
        if (line[0] && line[strlen(line) - 1] != '\n') {
            fputc('\n', stderr);
        }
        return 0;
    }

    return 1;
}

static int line_defines_name(const char *line, const char *name) {
    const char *p = skip_space(line);
    size_t name_len = strlen(name);

    if (*p == '\0' || *p == '\r' || *p == '\n' || *p == '!') {
        return 0;
    }

    if (starts_with_word_nocase(p, "integer") ||
        starts_with_word_nocase(p, "real") ||
        starts_with_word_nocase(p, "double") ||
        starts_with_word_nocase(p, "character") ||
        starts_with_word_nocase(p, "logical") ||
        starts_with_word_nocase(p, "complex")) {
        const char *decl_names = strstr(p, "::");
        p = decl_names ? decl_names + 2 : p;
        while (*p) {
            while (*p && !isalpha((unsigned char)*p) && *p != '_') {
                p++;
            }
            if (!*p) {
                break;
            }
            const char *start = p;
            while (identifier_char(*p)) {
                p++;
            }
            if (names_match(start, (size_t)(p - start), name)) {
                return 1;
            }
            while (*p == ' ' || *p == '\t') {
                p++;
            }
            if (*p == '(') {
                int depth = 1;
                p++;
                while (*p && depth > 0) {
                    if (*p == '(') depth++;
                    else if (*p == ')') depth--;
                    p++;
                }
            }
        }
        return 0;
    }

    if (names_match(p, name_len, name) && !identifier_char((unsigned char)p[name_len])) {
        p += name_len;
        while (*p == ' ' || *p == '\t') {
            p++;
        }
        if (*p == '=') {
            return 1;
        }
    }

    return 0;
}

static int source_defines_name(const char *source, const char *name) {
    const char *line = source;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (len >= sizeof(local)) {
            len = sizeof(local) - 1;
        }
        memcpy(local, line, len);
        local[len] = '\0';
        if (line_defines_name(local, name)) {
            return 1;
        }
        line = end ? end + 1 : NULL;
    }

    return 0;
}

static int is_immediate_expression_line(const char *line) {
    static const char *statement_words[] = {
        "program", "end", "subroutine", "function", "module", "use",
        "contains", "implicit", "integer", "real", "double", "character",
        "logical", "complex", "type", "if", "then", "else", "elseif",
        "do", "select", "case", "call", "print", "write", "read",
        "allocate", "deallocate", "return", "stop", "exit", "cycle",
        NULL
    };
    const char *p = skip_space(line);
    int i;

    if (*p == '\0' || *p == '\r' || *p == '\n' || *p == '.') {
        return 0;
    }
    if (contains_assignment(p) || strstr(p, "::")) {
        return 0;
    }
    for (i = 0; statement_words[i]; i++) {
        if (starts_with_word_nocase(p, statement_words[i])) {
            return 0;
        }
    }

    return 1;
}

static int execute_source_text(const char *text, int print_expr_statements, int suppress_output) {
    char *source = copy_string(text);
    OfortInterpreter *interp;
    int rc;

    if (!source) {
        return 2;
    }

    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }

    interp = ofort_create();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }
    ofort_set_print_expr_statements(interp, print_expr_statements);
    ofort_set_suppress_output(interp, suppress_output);

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        const char *output = ofort_get_output(interp);
        if (output && output[0] != '\0') {
            fputs(output, stdout);
        }
    } else {
        const char *error = ofort_get_error(interp);
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
    }

    ofort_destroy(interp);
    free(source);
    return rc == 0 ? 0 : 1;
}

static int execute_source_text_on_interpreter(OfortInterpreter *interp, const char *text,
                                              int print_expr_statements,
                                              int suppress_output) {
    char *source = copy_string(text);
    int rc;

    if (!source) {
        return 2;
    }

    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }

    ofort_reset(interp);
    ofort_set_print_expr_statements(interp, print_expr_statements);
    ofort_set_suppress_output(interp, suppress_output);

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        const char *output = ofort_get_output(interp);
        if (output && output[0] != '\0') {
            fputs(output, stdout);
        }
    } else {
        const char *error = ofort_get_error(interp);
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
    }

    free(source);
    return rc == 0 ? 0 : 1;
}

static int run_ofort_file_to_path(const char *source_path, const char *out_path) {
    char *source = read_file(source_path);
    FILE *fp;
    OfortInterpreter *interp;
    int rc;

    if (!source) {
        return 2;
    }
    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }

    interp = ofort_create();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        fp = fopen(out_path, "wb");
        if (!fp) {
            fprintf(stderr, "failed to open %s\n", out_path);
            ofort_destroy(interp);
            free(source);
            return 2;
        }
        fputs(ofort_get_output(interp), fp);
        fclose(fp);
    } else {
        const char *error = ofort_get_error(interp);
        fprintf(stderr, "ofort failed: %s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
    }

    ofort_destroy(interp);
    free(source);
    return rc == 0 ? 0 : 1;
}

static int check_ofort_file(const char *source_path) {
    char *source = read_file(source_path);
    OfortInterpreter *interp;
    int rc;

    if (!source) {
        return 2;
    }
    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }

    interp = ofort_create();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }

    rc = ofort_check(interp, source);
    if (rc == 0) {
        printf("ofort check passed\n");
    } else {
        const char *error = ofort_get_error(interp);
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "ofort check failed");
    }

    ofort_destroy(interp);
    free(source);
    return rc == 0 ? 0 : 1;
}

static int next_normalized_char(FILE *fp) {
    int c = fgetc(fp);
    if (c == '\r') {
        int next = fgetc(fp);
        if (next != '\n' && next != EOF) {
            ungetc(next, fp);
        }
        return '\n';
    }
    return c;
}

static int files_equal_normalized(const char *a_path, const char *b_path) {
    FILE *a = fopen(a_path, "rb");
    FILE *b = fopen(b_path, "rb");
    int ca;
    int cb;

    if (!a || !b) {
        if (a) fclose(a);
        if (b) fclose(b);
        return 0;
    }

    do {
        ca = next_normalized_char(a);
        cb = next_normalized_char(b);
        if (ca != cb) {
            fclose(a);
            fclose(b);
            return 0;
        }
    } while (ca != EOF && cb != EOF);

    fclose(a);
    fclose(b);
    return 1;
}

static void print_file_with_header(const char *header, const char *path) {
    FILE *fp = fopen(path, "rb");
    int c;

    fprintf(stderr, "%s\n", header);
    if (!fp) {
        fprintf(stderr, "(cannot open %s)\n", path);
        return;
    }
    while ((c = fgetc(fp)) != EOF) {
        fputc(c, stderr);
    }
    fclose(fp);
    fprintf(stderr, "\n");
}

static int check_with_gfortran(const char *source_path) {
    char stem[128];
    char exe_path[512];
    char ofort_out[512];
    char gfortran_out[512];
    char compile_cmd[2048];
    char run_cmd[2048];
    int rc;

    snprintf(stem, sizeof(stem), "ofort_check_%ld_%ld", (long)time(NULL), (long)GETPID());
    snprintf(exe_path, sizeof(exe_path), "%s.exe", stem);
    snprintf(ofort_out, sizeof(ofort_out), "%s.ofort.out", stem);
    snprintf(gfortran_out, sizeof(gfortran_out), "%s.gfortran.out", stem);

    rc = run_ofort_file_to_path(source_path, ofort_out);
    if (rc != 0) {
        remove(ofort_out);
        return rc;
    }

    snprintf(compile_cmd, sizeof(compile_cmd), "gfortran \"%s\" -o \"%s\"", source_path, exe_path);
    rc = system(compile_cmd);
    if (rc != 0) {
        fprintf(stderr, "gfortran compile failed\n");
        remove(ofort_out);
        remove(exe_path);
        return 1;
    }

    snprintf(run_cmd, sizeof(run_cmd), ".\\%s > \"%s\"", exe_path, gfortran_out);
    rc = system(run_cmd);
    if (rc != 0) {
        fprintf(stderr, "gfortran run failed\n");
        remove(ofort_out);
        remove(gfortran_out);
        remove(exe_path);
        return 1;
    }

    if (files_equal_normalized(ofort_out, gfortran_out)) {
        printf("ofort output matches gfortran\n");
        remove(ofort_out);
        remove(gfortran_out);
        remove(exe_path);
        return 0;
    }

    fprintf(stderr, "ofort output differs from gfortran\n");
    print_file_with_header("--- ofort stdout ---", ofort_out);
    print_file_with_header("--- gfortran stdout ---", gfortran_out);
    remove(ofort_out);
    remove(gfortran_out);
    remove(exe_path);
    return 1;
}

static char *copy_unexecuted_interactive_source(const char *source, size_t start) {
    size_t source_len = source ? strlen(source) : 0;

    if (!source || start >= source_len) {
        return copy_string("");
    }
    return copy_string(source + start);
}

static int execute_repl_pending_source(OfortInterpreter *interp, const char *source,
                                       size_t *executed_len) {
    char *pending;
    int rc;

    if (!source) {
        return 0;
    }
    pending = copy_unexecuted_interactive_source(source, *executed_len);
    if (!pending) {
        return 2;
    }
    if (pending[0] == '\0') {
        free(pending);
        return 0;
    }

    rc = execute_source_text_on_interpreter(interp, pending, 0, 1);
    if (rc == 0) {
        *executed_len = strlen(source);
    }
    free(pending);
    return rc;
}

static int execute_repl_expression(OfortInterpreter *interp, const char *source,
                                   size_t *executed_len, const char *expr_line) {
    int rc = execute_repl_pending_source(interp, source, executed_len);
    if (rc != 0) {
        return rc;
    }
    return execute_source_text_on_interpreter(interp, expr_line, 1, 1);
}

static char *copy_range_with_newline(const char *start, const char *end) {
    size_t len = (size_t)(end - start);
    int needs_newline = len == 0 || start[len - 1] != '\n';
    char *copy = (char *)malloc(len + (needs_newline ? 2 : 1));

    if (!copy) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }

    memcpy(copy, start, len);
    if (needs_newline) {
        copy[len++] = '\n';
    }
    copy[len] = '\0';
    return copy;
}

static int line_is_terminal_end(const char *start, const char *end) {
    while (start < end && isspace((unsigned char)*start)) {
        start++;
    }
    return end - start >= 3 &&
           tolower((unsigned char)start[0]) == 'e' &&
           tolower((unsigned char)start[1]) == 'n' &&
           tolower((unsigned char)start[2]) == 'd' &&
           (end - start == 3 || isspace((unsigned char)start[3]));
}

static char *strip_terminal_end_line(char *source) {
    char *end = source + strlen(source);
    char *line_start;
    char *footer = NULL;

    while (end > source && isspace((unsigned char)end[-1])) {
        end--;
    }
    if (end == source) {
        return NULL;
    }

    line_start = end;
    while (line_start > source && line_start[-1] != '\n') {
        line_start--;
    }

    if (line_is_terminal_end(line_start, end)) {
        footer = copy_range_with_newline(line_start, end);
        if (footer) {
            *line_start = '\0';
        }
    }

    return footer;
}

static int load_interactive_file(const char *path, char **buf, size_t *len,
                                 size_t *cap, char **footer) {
    char *source = read_file(path);
    char *new_footer;

    if (!source) {
        return 0;
    }

    normalize_newlines(source);
    new_footer = strip_terminal_end_line(source);
    free(*buf);
    free(*footer);
    *buf = source;
    *len = strlen(*buf);
    *cap = *len + 1;
    *footer = new_footer;
    printf("Loaded %s\n", path);
    return 1;
}

static const char *load_command_path(const char *line) {
    const char *p = skip_space(line);

    if (strncmp(p, ".load", 5) != 0 || !isspace((unsigned char)p[5])) {
        return NULL;
    }
    p += 5;
    p = skip_space(p);
    return (*p == '\0' || *p == '\r' || *p == '\n') ? NULL : p;
}

static const char *load_run_command_path(const char *line) {
    const char *p = skip_space(line);

    if (strncmp(p, ".load-run", 9) != 0 || !isspace((unsigned char)p[9])) {
        return NULL;
    }
    p += 9;
    p = skip_space(p);
    return (*p == '\0' || *p == '\r' || *p == '\n') ? NULL : p;
}

static void trim_line_end(char *text) {
    size_t len = strlen(text);
    while (len > 0 && (text[len - 1] == '\n' || text[len - 1] == '\r')) {
        text[--len] = '\0';
    }
}

static int run_interactive(const char *load_path, int run_after_load) {
    char line[4096];
    char *buf = NULL;
    char *footer = NULL;
    OfortInterpreter *repl_interp = NULL;
    size_t len = 0;
    size_t cap = 0;
    size_t executed_len = 0;
    int last_rc = 0;

    printf("Enter Fortran source.\n");
    printf("Commands: . runs, .runq runs and quits, .quit quits, .clear clears, .list lists, .load file loads, .load-run file loads/runs.\n");

    repl_interp = ofort_create();
    if (!repl_interp) {
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }

    if (load_path && !load_interactive_file(load_path, &buf, &len, &cap, &footer)) {
        free(buf);
        free(footer);
        ofort_destroy(repl_interp);
        return 2;
    }
    if (load_path && run_after_load) {
        last_rc = execute_source_text_on_interpreter(repl_interp, buf ? buf : "", 1, 0);
        if (last_rc == 0) {
            executed_len = strlen(buf ? buf : "");
        }
    }

    for (;;) {
        fputs("ofort> ", stdout);
        fflush(stdout);

        if (!fgets(line, sizeof(line), stdin)) {
            if (ferror(stdin)) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                fprintf(stderr, "failed to read stdin\n");
                return 2;
            }
            break;
        }

        if (is_command(line, ".")) {
            last_rc = execute_source_text_on_interpreter(repl_interp, buf ? buf : "", 1, 0);
            if (last_rc == 0) {
                executed_len = strlen(buf ? buf : "");
            }
            continue;
        }

        if (is_command(line, ".runq")) {
            last_rc = execute_source_text_on_interpreter(repl_interp, buf ? buf : "", 1, 0);
            if (last_rc == 0) {
                executed_len = strlen(buf ? buf : "");
            }
            if (save_interactive_source(buf ? buf : "", footer) != 0 && last_rc == 0) {
                last_rc = 1;
            }
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return last_rc;
        }

        if (is_command(line, ".quit")) {
            last_rc = save_interactive_source(buf ? buf : "", footer);
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return last_rc;
        }

        {
            const char *quit_name = NULL;
            if (line_is_name_only(line, "q")) {
                quit_name = "q";
            } else if (line_is_name_only(line, "quit")) {
                quit_name = "quit";
            }
            if (quit_name && !source_defines_name(buf ? buf : "", quit_name)) {
                last_rc = save_interactive_source(buf ? buf : "", footer);
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return last_rc;
            }
        }

        if (is_command(line, ".clear")) {
            free(buf);
            free(footer);
            buf = NULL;
            footer = NULL;
            len = 0;
            cap = 0;
            executed_len = 0;
            ofort_destroy(repl_interp);
            repl_interp = ofort_create();
            if (!repl_interp) {
                fprintf(stderr, "failed to create Fortran interpreter\n");
                return 2;
            }
            continue;
        }

        if (is_command(line, ".list")) {
            list_source(buf ? buf : "");
            if (footer && footer[0] != '\0') {
                fputs("   .  ", stdout);
                fputs(footer, stdout);
            }
            continue;
        }

        {
            const char *path = load_run_command_path(line);
            if (path) {
                char local_path[4096];
                snprintf(local_path, sizeof(local_path), "%s", path);
                trim_line_end(local_path);
                if (load_interactive_file(local_path, &buf, &len, &cap, &footer)) {
                    ofort_destroy(repl_interp);
                    repl_interp = ofort_create();
                    if (!repl_interp) {
                        fprintf(stderr, "failed to create Fortran interpreter\n");
                        free(buf);
                        free(footer);
                        return 2;
                    }
                    last_rc = execute_source_text_on_interpreter(repl_interp, buf ? buf : "", 1, 0);
                    executed_len = last_rc == 0 ? strlen(buf ? buf : "") : 0;
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            const char *path = load_command_path(line);
            if (path) {
                char local_path[4096];
                snprintf(local_path, sizeof(local_path), "%s", path);
                trim_line_end(local_path);
                if (!load_interactive_file(local_path, &buf, &len, &cap, &footer)) {
                    last_rc = 1;
                } else {
                    executed_len = 0;
                    ofort_destroy(repl_interp);
                    repl_interp = ofort_create();
                    if (!repl_interp) {
                        fprintf(stderr, "failed to create Fortran interpreter\n");
                        free(buf);
                        free(footer);
                        return 2;
                    }
                }
                continue;
            }
        }

        if (is_immediate_expression_line(line)) {
            last_rc = execute_repl_expression(repl_interp, buf ? buf : "", &executed_len, line);
            continue;
        }

        if (!validate_repl_line_before_append(buf ? buf : "", line)) {
            last_rc = 1;
            continue;
        }

        if (!add_repl_line_to_buffer(&buf, &len, &cap, line)) {
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return 2;
        }
    }

    if (buf && buf[0] != '\0') {
        last_rc = execute_source_text_on_interpreter(repl_interp, buf, 1, 0);
        if (save_interactive_source(buf, footer) != 0 && last_rc == 0) {
            last_rc = 1;
        }
    }

    free(buf);
    free(footer);
    ofort_destroy(repl_interp);
    return last_rc;
}

static char *read_file(const char *path) {
    char *source;
    FILE *fp = fopen(path, "rb");

    if (!fp) {
        fprintf(stderr, "failed to open %s\n", path);
        return NULL;
    }

    source = read_stream(fp, path);
    fclose(fp);
    return source;
}

static void normalize_newlines(char *source) {
    char *read = source;
    char *write = source;

    if ((unsigned char)read[0] == 0xef &&
        (unsigned char)read[1] == 0xbb &&
        (unsigned char)read[2] == 0xbf) {
        read += 3;
    }

    while (*read) {
        if (*read == '\r') {
            *write++ = '\n';
            read++;
            if (*read == '\n') {
                read++;
            }
        } else {
            *write++ = *read++;
        }
    }

    *write = '\0';
}

static int starts_with_keyword(const char *s, const char *kw) {
    size_t i;

    for (i = 0; kw[i]; i++) {
        if (tolower((unsigned char)s[i]) != tolower((unsigned char)kw[i])) {
            return 0;
        }
    }

    return s[i] == '\0' || isspace((unsigned char)s[i]);
}

static int has_program_unit_header(const char *source) {
    const char *p = source;

    for (;;) {
        while (*p == ' ' || *p == '\t' || *p == '\n') {
            p++;
        }

        if (*p == '!') {
            while (*p && *p != '\n') {
                p++;
            }
            continue;
        }

        break;
    }

    return starts_with_keyword(p, "program") ||
           starts_with_keyword(p, "module") ||
           starts_with_keyword(p, "subroutine") ||
           starts_with_keyword(p, "function") ||
           starts_with_keyword(p, "block data");
}

static int line_is_bare_end(const char *start, const char *end) {
    while (start < end && isspace((unsigned char)*start)) {
        start++;
    }

    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }

    return end - start == 3 &&
           tolower((unsigned char)start[0]) == 'e' &&
           tolower((unsigned char)start[1]) == 'n' &&
           tolower((unsigned char)start[2]) == 'd';
}

static void trim_terminal_bare_end(char *source) {
    char *end = source + strlen(source);
    char *line_start;

    while (end > source && isspace((unsigned char)end[-1])) {
        end--;
    }

    line_start = end;
    while (line_start > source && line_start[-1] != '\n') {
        line_start--;
    }

    if (line_is_bare_end(line_start, end)) {
        *line_start = '\0';
    }
}

static char *maybe_wrap_loose_source(char *source) {
    if (has_program_unit_header(source)) {
        return source;
    }

    trim_terminal_bare_end(source);
    return source;
}

static void print_usage(const char *program) {
    fprintf(stderr, "usage: %s [file.f90]\n", program);
    fprintf(stderr, "       %s --load file.f90\n", program);
    fprintf(stderr, "       %s --load-run file.f90\n", program);
    fprintf(stderr, "       %s --check file.f90\n", program);
    fprintf(stderr, "       %s --check-gfortran file.f90\n", program);
    fprintf(stderr, "       %s < file.f90\n", program);
    fprintf(stderr, "       with no file in a console, start an interactive session\n");
}

int main(int argc, char **argv) {
    char *source;
    const char *load_path = NULL;
    const char *syntax_check_path = NULL;
    const char *check_path = NULL;
    int run_after_load = 0;

    if (argc == 3 && strcmp(argv[1], "--load") == 0) {
        load_path = argv[2];
    } else if (argc == 3 && strcmp(argv[1], "--load-run") == 0) {
        load_path = argv[2];
        run_after_load = 1;
    } else if (argc == 3 && strcmp(argv[1], "--check") == 0) {
        syntax_check_path = argv[2];
    } else if (argc == 3 && strcmp(argv[1], "--check-gfortran") == 0) {
        check_path = argv[2];
    } else if (argc > 2) {
        print_usage(argv[0]);
        return 2;
    }

    if (check_path) {
        return check_with_gfortran(check_path);
    }

    if (syntax_check_path) {
        return check_ofort_file(syntax_check_path);
    }

    if (load_path) {
        return run_interactive(load_path, run_after_load);
    }

    if (argc == 2) {
        source = read_file(argv[1]);
    } else if (ISATTY(FILENO(stdin))) {
        return run_interactive(NULL, 0);
    } else {
        source = read_stream(stdin, "stdin");
    }
    if (!source) {
        return 2;
    }
    {
        int rc = execute_source_text(source, 0, 0);
        free(source);
        return rc;
    }
}
