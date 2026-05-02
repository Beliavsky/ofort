#include "ofort.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>
#include <math.h>
#include <stdint.h>

#ifdef _WIN32
#include <io.h>
#include <process.h>
#include <windows.h>
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
static int add_repl_line_to_buffer(char **buf, size_t *len, size_t *cap, const char *line);

typedef struct {
    const char **items;
    int count;
    int cap;
} PathList;

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

static int append_text_n(char **buf, size_t *len, size_t *cap, const char *text, size_t n) {
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

    if (n > 0) {
        memcpy(*buf + *len, text, n);
    }
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

static int command_starts_with(const char *line, const char *command) {
    size_t n = strlen(command);

    return strncmp(line, command, n) == 0 &&
           (line[n] == '\0' || line[n] == '\n' || line[n] == '\r' || isspace((unsigned char)line[n]));
}

static void free_split_args(char **args, int nargs) {
    for (int i = 0; i < nargs; i++) {
        free(args[i]);
    }
}

static int split_command_args(const char *text, char **args, int *nargs) {
    const char *p = text;
    *nargs = 0;

    while (p && *p) {
        char quote = '\0';
        char token[OFORT_MAX_STRLEN];
        size_t len = 0;

        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == '\0' || *p == '\n' || *p == '\r') break;

        if (*p == '\'' || *p == '"') {
            quote = *p++;
        }

        while (*p) {
            if (quote) {
                if (*p == quote) {
                    p++;
                    break;
                }
            } else if (isspace((unsigned char)*p)) {
                break;
            }
            if (len + 1 < sizeof(token)) {
                token[len++] = *p;
            }
            p++;
        }
        token[len] = '\0';

        if (*nargs >= OFORT_MAX_PARAMS) {
            fprintf(stderr, "too many program arguments; maximum is %d\n", OFORT_MAX_PARAMS);
            free_split_args(args, *nargs);
            *nargs = 0;
            return 0;
        }
        args[*nargs] = copy_string(token);
        if (!args[*nargs]) {
            free_split_args(args, *nargs);
            *nargs = 0;
            return 0;
        }
        (*nargs)++;
    }

    return 1;
}

static int parse_run_command(const char *line, const char *command, int *repeat_count,
                             char **args, int *nargs) {
    const char *p;
    char *endptr;
    long count;

    if (!command_starts_with(line, command)) {
        return 0;
    }

    *repeat_count = 1;
    *nargs = 0;
    p = skip_space(line + strlen(command));

    if (*p != '\0' && *p != '\n' && *p != '\r' && strncmp(p, "--", 2) != 0) {
        count = strtol(p, &endptr, 10);
        if (endptr == p || count < 1 || count > 1000000) {
            fprintf(stderr, "%s count must be a positive integer\n", command);
            return -1;
        }
        *repeat_count = (int)count;
        p = skip_space(endptr);
    }

    if (strncmp(p, "--", 2) == 0) {
        p = skip_space(p + 2);
        if (!split_command_args(p, args, nargs)) {
            return -1;
        }
    } else if (*p != '\0' && *p != '\n' && *p != '\r') {
        fprintf(stderr, "unexpected text after %s command; use -- before program arguments\n", command);
        return -1;
    }

    return 1;
}

static double monotonic_seconds(void) {
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

static void print_elapsed_time(double start) {
    fprintf(stderr, "time: %.6f s\n", monotonic_seconds() - start);
}

static void print_detailed_time(double setup, const OfortTiming *timing) {
    double total = setup;
    OfortTiming zero;

    if (!timing) {
        memset(&zero, 0, sizeof(zero));
        timing = &zero;
    }
    total += timing->total;
    fprintf(stderr, "time:\n");
    fprintf(stderr, "  setup:    %.6f s\n", setup);
    fprintf(stderr, "  lex:      %.6f s\n", timing->lex);
    fprintf(stderr, "  parse:    %.6f s\n", timing->parse);
    fprintf(stderr, "  register: %.6f s\n", timing->register_time);
    fprintf(stderr, "  execute:  %.6f s\n", timing->execute);
    fprintf(stderr, "  total:    %.6f s\n", total);
}

static void print_source_line_fragment(FILE *fp, const char *source, int line_no) {
    const char *p = source ? source : "";
    const char *start;
    const char *end;

    if (line_no < 1) return;
    for (int line = 1; line < line_no && *p; line++) {
        p = strchr(p, '\n');
        if (!p) return;
        p++;
    }
    start = p;
    end = strchr(start, '\n');
    if (!end) end = start + strlen(start);
    while (end > start && (end[-1] == '\r' || end[-1] == '\n')) end--;
    fprintf(fp, "%.*s", (int)(end - start), start);
}

static void print_line_profile(OfortInterpreter *interp, const char *source) {
    int n_entries = 0;
    OfortLineProfileEntry *entries;
    OfortTiming timing;
    double accounted = 0.0;
    double unprofiled;

    if (!interp) return;
    if (ofort_get_line_profile(interp, NULL, 0, &n_entries) != 0 || n_entries <= 0) return;
    entries = (OfortLineProfileEntry *)calloc((size_t)n_entries, sizeof(*entries));
    if (!entries) return;
    if (ofort_get_line_profile(interp, entries, n_entries, &n_entries) != 0) {
        free(entries);
        return;
    }

    fprintf(stderr, "\nline profile:\n");
    fprintf(stderr, "%6s %8s %12s  %s\n", "line", "count", "seconds", "source");
    for (int i = 0; i < n_entries; i++) {
        accounted += entries[i].seconds;
        fprintf(stderr, "%6d %8d %12.6f  ", entries[i].line, entries[i].count, entries[i].seconds);
        print_source_line_fragment(stderr, source, entries[i].line);
        fputc('\n', stderr);
    }
    if (ofort_get_timing(interp, &timing) == 0 && timing.execute > accounted) {
        unprofiled = timing.execute - accounted;
        if (unprofiled > 0.0000005) {
            fprintf(stderr, "%6s %8s %12.6f  %s\n", "-", "-", unprofiled, "(unprofiled interpreter overhead)");
        }
    }
    free(entries);
}

static int word_at_line_start(const char *line, int line_len, const char *word) {
    char buf[4096];
    int copy_len = line_len < (int)sizeof(buf) - 1 ? line_len : (int)sizeof(buf) - 1;

    memcpy(buf, line, (size_t)copy_len);
    buf[copy_len] = '\0';
    return starts_with_word_nocase(buf, word);
}

static int word_in_line(const char *line, int line_len, const char *word) {
    size_t word_len = strlen(word);

    for (int i = 0; i + (int)word_len <= line_len; i++) {
        int before_ok = i == 0 || !identifier_char((unsigned char)line[i - 1]);
        int after_ok = i + (int)word_len >= line_len || !identifier_char((unsigned char)line[i + word_len]);
        int same = 1;
        for (size_t j = 0; j < word_len; j++) {
            if (tolower((unsigned char)line[i + j]) != tolower((unsigned char)word[j])) {
                same = 0;
                break;
            }
        }
        if (before_ok && after_ok && same) {
            return 1;
        }
    }
    return 0;
}

static int line_is_blank_or_comment(const char *line, int line_len) {
    const char *p = line;
    const char *end = line + line_len;

    while (p < end && isspace((unsigned char)*p)) p++;
    return p == end || *p == '!';
}

static int line_deindents_before_print(const char *line, int line_len) {
    if (line_is_blank_or_comment(line, line_len)) return 0;
    return word_at_line_start(line, line_len, "end") ||
           word_at_line_start(line, line_len, "else") ||
           word_at_line_start(line, line_len, "case") ||
           word_at_line_start(line, line_len, "contains");
}

static int line_indents_after_print(const char *line, int line_len) {
    if (line_is_blank_or_comment(line, line_len)) return 0;
    if (word_at_line_start(line, line_len, "end")) return 0;
    if (word_at_line_start(line, line_len, "do")) return 1;
    if (word_at_line_start(line, line_len, "if") && word_in_line(line, line_len, "then")) return 1;
    if (word_at_line_start(line, line_len, "else")) return 1;
    if (word_at_line_start(line, line_len, "case")) return 1;
    if (word_at_line_start(line, line_len, "select")) return 1;
    if (word_at_line_start(line, line_len, "program")) return 1;
    if (word_at_line_start(line, line_len, "module")) return 1;
    if (word_at_line_start(line, line_len, "subroutine")) return 1;
    if (word_at_line_start(line, line_len, "function")) return 1;
    if (word_at_line_start(line, line_len, "contains")) return 1;
    return 0;
}

static void print_indent(int indent) {
    for (int i = 0; i < indent; i++) {
        fputs("  ", stdout);
    }
}

static void list_source(const char *source) {
    const char *line = source;
    int line_no = 1;
    int indent = 0;

    while (*line) {
        const char *end = strchr(line, '\n');
        int line_len = end ? (int)(end - line) : (int)strlen(line);
        const char *p = line;
        const char *line_end = line + line_len;
        int indent_after;

        while (p < line_end && isspace((unsigned char)*p)) p++;

        if (line_deindents_before_print(line, line_len) && indent > 0) {
            indent--;
        }
        indent_after = line_indents_after_print(line, line_len);

        if (end) {
            printf("%4d  ", line_no);
            print_indent(indent);
            printf("%.*s\n", (int)(line_end - p), p);
            line = end + 1;
        } else {
            printf("%4d  ", line_no);
            print_indent(indent);
            printf("%.*s\n", (int)(line_end - p), p);
            break;
        }
        if (indent_after) {
            indent++;
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

static void list_declarations(const char *source) {
    const char *line = source;
    int line_no = 1;
    int indent = 0;

    while (*line) {
        const char *end = strchr(line, '\n');
        int line_len = end ? (int)(end - line) : (int)strlen(line);
        const char *p = line;
        const char *line_end = line + line_len;
        int indent_after;
        char local[4096];
        int copy_len = line_len < (int)sizeof(local) - 1 ? line_len : (int)sizeof(local) - 1;

        memcpy(local, line, (size_t)copy_len);
        local[copy_len] = '\0';

        while (p < line_end && isspace((unsigned char)*p)) p++;

        if (line_deindents_before_print(line, line_len) && indent > 0) {
            indent--;
        }
        indent_after = line_indents_after_print(line, line_len);

        if (is_repl_declaration_line(skip_space(local))) {
            printf("%4d  ", line_no);
            print_indent(indent);
            printf("%.*s\n", (int)(line_end - p), p);
        }

        if (indent_after) {
            indent++;
        }
        if (!end) {
            break;
        }
        line = end + 1;
        line_no++;
    }
}

static int is_blank_or_comment_line(const char *line) {
    const char *p = skip_space(line);
    return *p == '\0' || *p == '\r' || *p == '\n' || *p == '!';
}

static void copy_logical_line(char *dst, size_t dst_size, const char *line) {
    size_t len;

    if (dst_size == 0) {
        return;
    }
    len = strcspn(line ? line : "", "\r\n");
    if (len >= dst_size) {
        len = dst_size - 1;
    }
    memcpy(dst, line ? line : "", len);
    dst[len] = '\0';
}

static void lower_logical_line(char *dst, size_t dst_size, const char *line) {
    size_t i;

    copy_logical_line(dst, dst_size, skip_space(line ? line : ""));
    for (i = 0; dst[i]; i++) {
        dst[i] = (char)tolower((unsigned char)dst[i]);
    }
}

static int line_starts_word_lower(const char *line, const char *word) {
    size_t n = strlen(word);
    return strncmp(line, word, n) == 0 && !identifier_char((unsigned char)line[n]);
}

static int line_contains_word_lower(const char *line, const char *word) {
    size_t n = strlen(word);
    const char *p = line;

    while ((p = strstr(p, word)) != NULL) {
        int before_ok = p == line || !identifier_char((unsigned char)p[-1]);
        int after_ok = !identifier_char((unsigned char)p[n]);
        if (before_ok && after_ok) {
            return 1;
        }
        p += n;
    }
    return 0;
}

static int repl_line_pre_dedent(const char *line) {
    char lower[4096];

    lower_logical_line(lower, sizeof(lower), line);
    if (lower[0] == '\0' || lower[0] == '!') {
        return 0;
    }
    return line_starts_word_lower(lower, "end") ||
           line_starts_word_lower(lower, "else") ||
           line_starts_word_lower(lower, "case") ||
           line_starts_word_lower(lower, "contains");
}

static int repl_line_post_indent(const char *line) {
    char lower[4096];

    lower_logical_line(lower, sizeof(lower), line);
    if (lower[0] == '\0' || lower[0] == '!') {
        return 0;
    }
    if (line_starts_word_lower(lower, "end")) {
        return 0;
    }
    if (line_starts_word_lower(lower, "else") ||
        line_starts_word_lower(lower, "case") ||
        line_starts_word_lower(lower, "contains")) {
        return 1;
    }
    if (line_starts_word_lower(lower, "do")) {
        return 1;
    }
    if (line_starts_word_lower(lower, "if") && line_contains_word_lower(lower, "then")) {
        return 1;
    }
    if (line_starts_word_lower(lower, "select") ||
        line_starts_word_lower(lower, "program") ||
        line_starts_word_lower(lower, "subroutine") ||
        line_starts_word_lower(lower, "function") ||
        line_starts_word_lower(lower, "module")) {
        return 1;
    }
    if (line_starts_word_lower(lower, "type") && strstr(lower, "::") == NULL) {
        return 1;
    }
    return 0;
}

static int append_indented_repl_line(char **buf, size_t *len, size_t *cap,
                                     const char *line, int indent_level) {
    char indented[8192];
    const char *text = skip_space(line);
    size_t text_len = strlen(text);
    size_t pos = 0;

    if (indent_level < 0) {
        indent_level = 0;
    }
    for (int i = 0; i < indent_level * 2 && pos + 1 < sizeof(indented); i++) {
        indented[pos++] = ' ';
    }
    if (text_len > sizeof(indented) - pos - 1) {
        text_len = sizeof(indented) - pos - 1;
    }
    memcpy(indented + pos, text, text_len);
    pos += text_len;
    indented[pos] = '\0';

    return add_repl_line_to_buffer(buf, len, cap, indented);
}

static int source_indent_level(const char *source) {
    const char *line = source;
    int indent = 0;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (len >= sizeof(local)) {
            len = sizeof(local) - 1;
        }
        memcpy(local, line, len);
        local[len] = '\0';
        if (repl_line_pre_dedent(local) && indent > 0) {
            indent--;
        }
        if (repl_line_post_indent(local)) {
            indent++;
        }
        line = end ? end + 1 : NULL;
    }

    return indent;
}

static int source_inside_procedure(const char *source) {
    const char *line = source;
    int depth = 0;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        char lower[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (len >= sizeof(local)) len = sizeof(local) - 1;
        memcpy(local, line, len);
        local[len] = '\0';
        lower_logical_line(lower, sizeof(lower), local);
        if (line_starts_word_lower(lower, "end") &&
            (line_contains_word_lower(lower, "subroutine") ||
             line_contains_word_lower(lower, "function"))) {
            if (depth > 0) depth--;
        } else if (line_starts_word_lower(lower, "subroutine") ||
                   line_starts_word_lower(lower, "function")) {
            depth++;
        }
        line = end ? end + 1 : NULL;
    }

    return depth > 0;
}

static int repl_line_has_implicit_save(const char *line, char *name, size_t name_size) {
    char lower[4096];
    const char *p;
    const char *dc;
    const char *eq;

    lower_logical_line(lower, sizeof(lower), line);
    if (!(line_starts_word_lower(lower, "integer") ||
          line_starts_word_lower(lower, "real") ||
          line_starts_word_lower(lower, "double") ||
          line_starts_word_lower(lower, "character") ||
          line_starts_word_lower(lower, "logical") ||
          line_starts_word_lower(lower, "complex"))) {
        return 0;
    }
    if (!strstr(lower, "::") || !strchr(lower, '=')) return 0;
    if (line_contains_word_lower(lower, "save") || line_contains_word_lower(lower, "parameter")) return 0;

    dc = strstr(line, "::");
    eq = strchr(dc ? dc + 2 : line, '=');
    if (!dc || !eq) return 0;
    p = dc + 2;
    while (p < eq && isspace((unsigned char)*p)) p++;
    if (!(isalpha((unsigned char)*p) || *p == '_')) return 0;
    {
        const char *start = p;
        while (p < eq && identifier_char(*p)) p++;
        if (name_size > 0) {
            size_t len = (size_t)(p - start);
            if (len >= name_size) len = name_size - 1;
            memcpy(name, start, len);
            name[len] = '\0';
        }
    }
    return 1;
}

static int is_buffer_declaration_line(const char *line) {
    const char *p = skip_space(line);
    return is_blank_or_comment_line(line) ||
           is_repl_declaration_line(line) ||
           starts_with_word_nocase(p, "program") ||
           starts_with_word_nocase(p, "module") ||
           starts_with_word_nocase(p, "subroutine") ||
           starts_with_word_nocase(p, "function");
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

static int g_implicit_typing = 0;
static int g_warnings_enabled = 1;
static int g_time_detail = 0;
static int g_fast_mode = 0;
static int g_specialized_fast_paths = 1;
static int g_line_profile = 0;

static OfortInterpreter *create_ofort_interpreter(void) {
    OfortInterpreter *interp = ofort_create();
    if (interp) {
        ofort_set_implicit_typing(interp, g_implicit_typing);
        ofort_set_warnings_enabled(interp, g_warnings_enabled);
        ofort_set_fast_mode(interp, g_fast_mode);
        ofort_set_specialized_fast_paths(interp, g_specialized_fast_paths);
        ofort_set_line_profile_enabled(interp, g_line_profile);
    }
    return interp;
}

static int execute_source_text(const char *text, int print_expr_statements, int suppress_output,
                               int command_argc, char **command_args, double setup_start) {
    char *source = copy_string(text);
    OfortInterpreter *interp;
    int rc;
    double setup_elapsed;

    if (!source) {
        return 2;
    }

    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }
    setup_elapsed = monotonic_seconds() - setup_start;

    interp = create_ofort_interpreter();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }
    ofort_set_print_expr_statements(interp, print_expr_statements);
    ofort_set_suppress_output(interp, suppress_output);
    ofort_set_command_args(interp, command_argc, (const char *const *)command_args);

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        const char *warnings = ofort_get_warnings(interp);
        const char *output = ofort_get_output(interp);
        if (g_time_detail) {
            OfortTiming timing;
            if (ofort_get_timing(interp, &timing) == 0) {
                print_detailed_time(setup_elapsed, &timing);
            }
        }
        if (warnings && warnings[0] != '\0') {
            fputs(warnings, stderr);
        }
        if (output && output[0] != '\0') {
            fputs(output, stdout);
        }
        if (g_line_profile) {
            print_line_profile(interp, source);
        }
    } else {
        const char *error = ofort_get_error(interp);
        if (g_time_detail) {
            OfortTiming timing;
            if (ofort_get_timing(interp, &timing) == 0) {
                print_detailed_time(setup_elapsed, &timing);
            }
        }
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
    }

    ofort_destroy(interp);
    free(source);
    return rc == 0 ? 0 : 1;
}

static int execute_source_text_on_interpreter(OfortInterpreter *interp, const char *text,
                                              int print_expr_statements,
                                              int suppress_output,
                                              int command_argc,
                                              char **command_args) {
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
    ofort_set_command_args(interp, command_argc, (const char *const *)command_args);

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        const char *warnings = ofort_get_warnings(interp);
        const char *output = ofort_get_output(interp);
        if (warnings && warnings[0] != '\0') {
            fputs(warnings, stderr);
        }
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

    interp = create_ofort_interpreter();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }

    rc = ofort_execute(interp, source);
    if (rc == 0) {
        const char *warnings = ofort_get_warnings(interp);
        if (warnings && warnings[0] != '\0') {
            fputs(warnings, stderr);
        }
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
    double setup_start = monotonic_seconds();
    char *source = read_file(source_path);
    OfortInterpreter *interp;
    int rc;
    double setup_elapsed;

    if (!source) {
        return 2;
    }
    normalize_newlines(source);
    source = maybe_wrap_loose_source(source);
    if (!source) {
        return 2;
    }
    setup_elapsed = monotonic_seconds() - setup_start;

    interp = create_ofort_interpreter();
    if (!interp) {
        free(source);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return 2;
    }

    rc = ofort_check(interp, source);
    if (g_time_detail) {
        OfortTiming timing;
        if (ofort_get_timing(interp, &timing) == 0) {
            print_detailed_time(setup_elapsed, &timing);
        }
    }
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

static int run_each_file(const char *const *paths, int npaths, int syntax_check,
                         int command_argc, char **command_args, int time_operation) {
    int failures = 0;

    for (int i = 0; i < npaths; i++) {
        int rc;
        double start = monotonic_seconds();
        if (i > 0) {
            printf("\n");
        }
        printf("==> %s\n", paths[i]);
        fflush(stdout);

        if (syntax_check) {
            rc = check_ofort_file(paths[i]);
        } else {
            char *source = read_file(paths[i]);
            if (!source) {
                rc = 2;
            } else {
                rc = execute_source_text(source, 0, 0, command_argc, command_args, start);
                free(source);
            }
        }
        if (time_operation && !g_time_detail) {
            print_elapsed_time(start);
        }
        if (rc != 0) {
            failures++;
        }
    }

    return failures == 0 ? 0 : 1;
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

    rc = execute_source_text_on_interpreter(interp, pending, 0, 1, 0, NULL);
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
    return execute_source_text_on_interpreter(interp, expr_line, 1, 1, 0, NULL);
}

static int execute_repl_run(OfortInterpreter **interp, const char *source, int repeat_count,
                            int command_argc, char **command_args) {
    int last_rc = 0;

    if (repeat_count < 1) repeat_count = 1;
    for (int i = 0; i < repeat_count; i++) {
        ofort_destroy(*interp);
        *interp = create_ofort_interpreter();
        if (!*interp) {
            fprintf(stderr, "failed to create Fortran interpreter\n");
            return 2;
        }
        last_rc = execute_source_text_on_interpreter(
            *interp, source ? source : "", 1, 0, command_argc, command_args);
        if (last_rc != 0) {
            return last_rc;
        }
    }

    return last_rc;
}

static int execute_repl_timed_run(OfortInterpreter **interp, const char *source, int repeat_count,
                                  int command_argc, char **command_args) {
    double total = 0.0;
    double sumsq = 0.0;
    double min_time = 0.0;
    double max_time = 0.0;
    int last_rc = 0;

    if (repeat_count < 1) repeat_count = 1;
    for (int i = 0; i < repeat_count; i++) {
        double start;
        double elapsed;

        ofort_destroy(*interp);
        *interp = create_ofort_interpreter();
        if (!*interp) {
            fprintf(stderr, "failed to create Fortran interpreter\n");
            return 2;
        }
        start = monotonic_seconds();
        last_rc = execute_source_text_on_interpreter(
            *interp, source ? source : "", 1, 0, command_argc, command_args);
        elapsed = monotonic_seconds() - start;
        if (last_rc != 0) {
            return last_rc;
        }
        total += elapsed;
        sumsq += elapsed * elapsed;
        if (i == 0 || elapsed < min_time) {
            min_time = elapsed;
        }
        if (i == 0 || elapsed > max_time) {
            max_time = elapsed;
        }
    }

    if (repeat_count == 1) {
        printf("\n%12s\n", "total");
        printf("%12.6f s\n", total);
    } else {
        double avg = total / repeat_count;
        double variance = (sumsq - (total * total) / repeat_count) / (repeat_count - 1);
        double sd = sqrt(variance > 0.0 ? variance : 0.0);

        printf("\n%12s %12s %12s %12s %12s\n", "total", "avg", "sd", "min", "max");
        printf("%12.6f %12.6f %12.6f %12.6f %12.6f s\n",
               total, avg, sd, min_time, max_time);
    }
    return last_rc;
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

static int repl_named_command_args(const char *line, const char *command, char **args, int *nargs) {
    const char *p = skip_space(line);

    if (!command_starts_with(p, command)) {
        return 0;
    }
    p = skip_space(p + strlen(command));
    if (!split_command_args(p, args, nargs)) {
        return -1;
    }
    return 1;
}

static int source_line_count(const char *source) {
    const char *p = source;
    int count = 0;

    while (p && *p) {
        count++;
        p = strchr(p, '\n');
        if (!p) break;
        p++;
    }
    return count;
}

static const char *source_line_start(const char *source, int line_no) {
    const char *p = source;

    if (line_no <= 1) return source;
    for (int i = 1; p && *p && i < line_no; i++) {
        p = strchr(p, '\n');
        if (!p) return NULL;
        p++;
    }
    return p;
}

static int parse_delete_range(const char *line, int *first_line, int *last_line) {
    const char *p = skip_space(line);
    char *endptr;
    long first = 0;
    long last = 0;
    int has_first = 0;
    int has_last = 0;

    if (!command_starts_with(p, ".del")) return 0;
    p = skip_space(p + 4);
    if (*p == '\0' || *p == '\r' || *p == '\n') {
        fprintf(stderr, ".del requires a line number or range\n");
        return -1;
    }

    if (*p != ':') {
        first = strtol(p, &endptr, 10);
        if (endptr == p || first < 1) {
            fprintf(stderr, "invalid .del range\n");
            return -1;
        }
        has_first = 1;
        p = skip_space(endptr);
    }

    if (*p == ':') {
        p = skip_space(p + 1);
        if (*p != '\0' && *p != '\r' && *p != '\n') {
            last = strtol(p, &endptr, 10);
            if (endptr == p || last < 1) {
                fprintf(stderr, "invalid .del range\n");
                return -1;
            }
            has_last = 1;
            p = skip_space(endptr);
        }
    } else if (has_first) {
        last = first;
        has_last = 1;
    } else {
        fprintf(stderr, "invalid .del range\n");
        return -1;
    }

    if (*p != '\0' && *p != '\r' && *p != '\n') {
        fprintf(stderr, "unexpected text after .del range\n");
        return -1;
    }

    *first_line = has_first ? (int)first : 1;
    *last_line = has_last ? (int)last : -1;
    return 1;
}

static int delete_source_lines(char **buf, size_t *len, int first_line, int last_line) {
    int n_lines = source_line_count(*buf ? *buf : "");
    const char *start;
    const char *end;
    size_t start_pos;
    size_t end_pos;

    if (last_line < 0) last_line = n_lines;
    if (first_line < 1 || last_line < first_line || last_line > n_lines) {
        fprintf(stderr, ".del range is outside the editable source buffer\n");
        return 0;
    }

    start = source_line_start(*buf, first_line);
    end = source_line_start(*buf, last_line + 1);
    if (!start) {
        fprintf(stderr, ".del range is outside the editable source buffer\n");
        return 0;
    }
    if (!end) {
        end = *buf + *len;
    }

    start_pos = (size_t)(start - *buf);
    end_pos = (size_t)(end - *buf);
    memmove(*buf + start_pos, *buf + end_pos, *len - end_pos + 1);
    *len -= end_pos - start_pos;
    return 1;
}

static int parse_line_edit_command(const char *line, const char *command,
                                   int *line_no, const char **text_out) {
    const char *p = skip_space(line);
    char *endptr;
    long n;

    if (!command_starts_with(p, command)) return 0;
    p = skip_space(p + strlen(command));
    if (*p == '\0' || *p == '\r' || *p == '\n') {
        fprintf(stderr, "%s requires a line number and text\n", command);
        return -1;
    }

    n = strtol(p, &endptr, 10);
    if (endptr == p || n < 1) {
        fprintf(stderr, "invalid %s line number\n", command);
        return -1;
    }
    p = skip_space(endptr);
    if (*p == '\0' || *p == '\r' || *p == '\n') {
        fprintf(stderr, "%s requires text\n", command);
        return -1;
    }

    *line_no = (int)n;
    *text_out = p;
    return 1;
}

static char *copy_edit_text_with_newline(const char *text) {
    size_t len = strcspn(text ? text : "", "\r\n");
    char *copy = (char *)malloc(len + 2);

    if (!copy) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }
    if (len > 0) memcpy(copy, text, len);
    copy[len++] = '\n';
    copy[len] = '\0';
    return copy;
}

static int path_list_add(PathList *list, const char *path) {
    const char **new_items;
    char *copy;

    if (list->count >= list->cap) {
        int new_cap = list->cap ? list->cap * 2 : 16;
        new_items = (const char **)realloc(list->items, (size_t)new_cap * sizeof(*list->items));
        if (!new_items) {
            fprintf(stderr, "out of memory\n");
            return 0;
        }
        list->items = new_items;
        list->cap = new_cap;
    }
    copy = copy_string(path);
    if (!copy) return 0;
    list->items[list->count++] = copy;
    return 1;
}

static void path_list_free(PathList *list) {
    if (!list) return;
    for (int i = 0; i < list->count; i++) {
        free((void *)list->items[i]);
    }
    free(list->items);
    list->items = NULL;
    list->count = 0;
    list->cap = 0;
}

static int has_glob_wildcard(const char *path) {
    return path && (strchr(path, '*') || strchr(path, '?'));
}

#ifdef _WIN32
static int expand_windows_glob(PathList *list, const char *pattern) {
    intptr_t handle;
    struct _finddata_t data;
    char dir[1024];
    const char *slash1;
    const char *slash2;
    const char *base;
    size_t dir_len;
    int matched = 0;

    if (!has_glob_wildcard(pattern)) {
        return path_list_add(list, pattern);
    }

    slash1 = strrchr(pattern, '\\');
    slash2 = strrchr(pattern, '/');
    base = slash1 > slash2 ? slash1 : slash2;
    if (base) {
        dir_len = (size_t)(base - pattern + 1);
        if (dir_len >= sizeof(dir)) {
            fprintf(stderr, "path too long: %s\n", pattern);
            return 0;
        }
        memcpy(dir, pattern, dir_len);
        dir[dir_len] = '\0';
    } else {
        dir[0] = '\0';
    }

    handle = _findfirst(pattern, &data);
    if (handle == -1) {
        return path_list_add(list, pattern);
    }

    do {
        char full[2048];
        if (data.attrib & _A_SUBDIR) continue;
        snprintf(full, sizeof(full), "%s%s", dir, data.name);
        if (!path_list_add(list, full)) {
            _findclose(handle);
            return 0;
        }
        matched = 1;
    } while (_findnext(handle, &data) == 0);

    _findclose(handle);
    if (!matched) return path_list_add(list, pattern);
    return 1;
}
#else
static int expand_windows_glob(PathList *list, const char *pattern) {
    return path_list_add(list, pattern);
}
#endif

static int insert_source_line(char **buf, size_t *len, size_t *cap, int line_no, const char *text) {
    int n_lines = source_line_count(*buf ? *buf : "");
    const char *pos_ptr;
    size_t pos;
    char *line_text;
    int ok;

    if (line_no < 1 || line_no > n_lines + 1) {
        fprintf(stderr, ".ins line is outside the editable source buffer\n");
        return 0;
    }
    pos_ptr = (line_no == n_lines + 1) ? (*buf ? *buf + *len : NULL) : source_line_start(*buf ? *buf : "", line_no);
    if (!pos_ptr) {
        fprintf(stderr, ".ins line is outside the editable source buffer\n");
        return 0;
    }
    pos = *buf ? (size_t)(pos_ptr - *buf) : 0;
    line_text = copy_edit_text_with_newline(text);
    if (!line_text) return 0;
    ok = insert_text_at(buf, len, cap, pos, line_text);
    free(line_text);
    return ok;
}

static int replace_source_line(char **buf, size_t *len, size_t *cap, int line_no, const char *text) {
    int n_lines = source_line_count(*buf ? *buf : "");

    if (line_no < 1 || line_no > n_lines) {
        fprintf(stderr, ".rep line is outside the editable source buffer\n");
        return 0;
    }
    if (!delete_source_lines(buf, len, line_no, line_no)) {
        return 0;
    }
    return insert_source_line(buf, len, cap, line_no, text);
}

static int valid_identifier_name(const char *name) {
    const char *p = name;

    if (!name || !(isalpha((unsigned char)*p) || *p == '_')) {
        return 0;
    }
    p++;
    while (*p) {
        if (!identifier_char((unsigned char)*p)) {
            return 0;
        }
        p++;
    }
    return 1;
}

static const char *skip_string_literal(const char *p) {
    char quote = *p++;

    while (*p) {
        if (*p == quote) {
            if (p[1] == quote) {
                p += 2;
                continue;
            }
            p++;
            break;
        }
        p++;
    }
    return p;
}

static int source_identifier_exists(const char *source, const char *name) {
    const char *p = source ? source : "";

    while (*p) {
        if (*p == '\'' || *p == '"') {
            p = skip_string_literal(p);
        } else if (*p == '!') {
            while (*p && *p != '\n') p++;
        } else if (isalpha((unsigned char)*p) || *p == '_') {
            const char *start = p;
            while (identifier_char((unsigned char)*p)) p++;
            if (names_match(start, (size_t)(p - start), name)) {
                return 1;
            }
        } else {
            p++;
        }
    }
    return 0;
}

static int rename_source_identifier(char **buf, size_t *len, size_t *cap,
                                    const char *old_name, const char *new_name) {
    const char *src = *buf ? *buf : "";
    const char *p = src;
    char *new_buf = NULL;
    size_t new_len = 0;
    size_t new_cap = 0;
    int renamed = 0;

    if (!valid_identifier_name(old_name) || !valid_identifier_name(new_name)) {
        fprintf(stderr, ".rename requires valid identifier names\n");
        return 0;
    }
    if (names_match(old_name, strlen(old_name), new_name)) {
        fprintf(stderr, ".rename old and new names are the same\n");
        return 0;
    }
    if (source_identifier_exists(src, new_name)) {
        fprintf(stderr, ".rename: %s already exists\n", new_name);
        return 0;
    }

    while (*p) {
        if (*p == '\'' || *p == '"') {
            const char *end = skip_string_literal(p);
            if (!append_text_n(&new_buf, &new_len, &new_cap, p, (size_t)(end - p))) {
                free(new_buf);
                return 0;
            }
            p = end;
        } else if (*p == '!') {
            const char *end = p;
            while (*end && *end != '\n') end++;
            if (!append_text_n(&new_buf, &new_len, &new_cap, p, (size_t)(end - p))) {
                free(new_buf);
                return 0;
            }
            p = end;
        } else if (isalpha((unsigned char)*p) || *p == '_') {
            const char *start = p;
            while (identifier_char((unsigned char)*p)) p++;
            if (names_match(start, (size_t)(p - start), old_name)) {
                if (!append_text(&new_buf, &new_len, &new_cap, new_name)) {
                    free(new_buf);
                    return 0;
                }
                renamed = 1;
            } else if (!append_text_n(&new_buf, &new_len, &new_cap, start, (size_t)(p - start))) {
                free(new_buf);
                return 0;
            }
        } else {
            if (!append_text_n(&new_buf, &new_len, &new_cap, p, 1)) {
                free(new_buf);
                return 0;
            }
            p++;
        }
    }

    if (!renamed) {
        fprintf(stderr, ".rename: %s not found\n", old_name);
        free(new_buf);
        return 0;
    }

    free(*buf);
    *buf = new_buf;
    *len = new_len;
    *cap = new_cap;
    return 1;
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
    printf("Commands: . runs, .run [n] [-- args] repeats, .time [n] [-- args] times, .runq [n] [-- args] runs and quits, .quit quits, .clear clears, .del n[:m] deletes lines, .ins n text inserts, .rep n text replaces, .rename old new renames, .list lists, .decl lists declarations, .vars [names] lists values, .info [names] lists details, .shapes [names] lists array shapes, .sizes [names] lists array sizes, .stats [names] lists array stats, .load file loads, .load-run file loads/runs.\n");

    repl_interp = create_ofort_interpreter();
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
        char *effective = make_effective_source(buf ? buf : "", footer);
        if (!effective) {
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return 2;
        }
        last_rc = execute_source_text_on_interpreter(repl_interp, effective, 1, 0, 0, NULL);
        free(effective);
        if (last_rc == 0) {
            executed_len = strlen(buf ? buf : "");
        }
    }

    for (;;) {
        int prompt_indent = source_indent_level(buf ? buf : "");

        fputs("ofort> ", stdout);
        for (int i = 0; i < prompt_indent * 2; i++) {
            fputc(' ', stdout);
        }
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
            char *effective = make_effective_source(buf ? buf : "", footer);
            if (!effective) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            last_rc = execute_source_text_on_interpreter(repl_interp, effective, 1, 0, 0, NULL);
            free(effective);
            if (last_rc == 0) {
                executed_len = strlen(buf ? buf : "");
            }
            continue;
        }

        {
            char *run_args[OFORT_MAX_PARAMS];
            int run_nargs = 0;
            int repeat_count = 1;
            int parsed = parse_run_command(line, ".run", &repeat_count, run_args, &run_nargs);
            if (parsed != 0) {
                if (parsed > 0) {
                    char *effective = make_effective_source(buf ? buf : "", footer);
                    if (!effective) {
                        free_split_args(run_args, run_nargs);
                        free(buf);
                        free(footer);
                        ofort_destroy(repl_interp);
                        return 2;
                    }
                    last_rc = execute_repl_run(&repl_interp, effective, repeat_count, run_nargs, run_args);
                    free(effective);
                    if (last_rc == 0) {
                        executed_len = strlen(buf ? buf : "");
                    }
                    free_split_args(run_args, run_nargs);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *run_args[OFORT_MAX_PARAMS];
            int run_nargs = 0;
            int repeat_count = 1;
            int parsed = parse_run_command(line, ".time", &repeat_count, run_args, &run_nargs);
            if (parsed != 0) {
                if (parsed > 0) {
                    char *effective = make_effective_source(buf ? buf : "", footer);
                    if (!effective) {
                        free_split_args(run_args, run_nargs);
                        free(buf);
                        free(footer);
                        ofort_destroy(repl_interp);
                        return 2;
                    }
                    last_rc = execute_repl_timed_run(&repl_interp, effective, repeat_count, run_nargs, run_args);
                    free(effective);
                    if (last_rc == 0) {
                        executed_len = strlen(buf ? buf : "");
                    }
                    free_split_args(run_args, run_nargs);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *run_args[OFORT_MAX_PARAMS];
            int run_nargs = 0;
            int repeat_count = 1;
            int parsed = parse_run_command(line, ".runq", &repeat_count, run_args, &run_nargs);
            if (parsed == 0) {
                parsed = is_command(line, ".runq") ? 1 : 0;
            }
            if (parsed != 0) {
                if (parsed > 0) {
                    char *effective = make_effective_source(buf ? buf : "", footer);
                    if (!effective) {
                        free_split_args(run_args, run_nargs);
                        free(buf);
                        free(footer);
                        ofort_destroy(repl_interp);
                        return 2;
                    }
                    last_rc = execute_repl_run(&repl_interp, effective, repeat_count, run_nargs, run_args);
                    free(effective);
                    free_split_args(run_args, run_nargs);
                } else {
                    last_rc = 1;
                }
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
            repl_interp = create_ofort_interpreter();
            if (!repl_interp) {
                fprintf(stderr, "failed to create Fortran interpreter\n");
                return 2;
            }
            continue;
        }

        {
            int first_line = 0;
            int last_line = 0;
            int parsed = parse_delete_range(line, &first_line, &last_line);
            if (parsed != 0) {
                if (parsed > 0) {
                    if (delete_source_lines(&buf, &len, first_line, last_line)) {
                        executed_len = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_ofort_interpreter();
                        if (!repl_interp) {
                            fprintf(stderr, "failed to create Fortran interpreter\n");
                            free(buf);
                            free(footer);
                            return 2;
                        }
                        last_rc = 0;
                    } else {
                        last_rc = 1;
                    }
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            int edit_line = 0;
            const char *edit_text = NULL;
            int parsed = parse_line_edit_command(line, ".ins", &edit_line, &edit_text);
            if (parsed != 0) {
                if (parsed > 0) {
                    if (insert_source_line(&buf, &len, &cap, edit_line, edit_text)) {
                        executed_len = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_ofort_interpreter();
                        if (!repl_interp) {
                            fprintf(stderr, "failed to create Fortran interpreter\n");
                            free(buf);
                            free(footer);
                            return 2;
                        }
                        last_rc = 0;
                    } else {
                        last_rc = 1;
                    }
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            int edit_line = 0;
            const char *edit_text = NULL;
            int parsed = parse_line_edit_command(line, ".rep", &edit_line, &edit_text);
            if (parsed != 0) {
                if (parsed > 0) {
                    if (replace_source_line(&buf, &len, &cap, edit_line, edit_text)) {
                        executed_len = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_ofort_interpreter();
                        if (!repl_interp) {
                            fprintf(stderr, "failed to create Fortran interpreter\n");
                            free(buf);
                            free(footer);
                            return 2;
                        }
                        last_rc = 0;
                    } else {
                        last_rc = 1;
                    }
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *rename_args[OFORT_MAX_PARAMS];
            int n_rename_args = 0;
            int parsed = repl_named_command_args(line, ".rename", rename_args, &n_rename_args);
            if (parsed != 0) {
                if (parsed > 0) {
                    if (n_rename_args != 2) {
                        fprintf(stderr, ".rename requires old and new names\n");
                        last_rc = 1;
                    } else if (rename_source_identifier(&buf, &len, &cap, rename_args[0], rename_args[1])) {
                        executed_len = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_ofort_interpreter();
                        if (!repl_interp) {
                            fprintf(stderr, "failed to create Fortran interpreter\n");
                            free_split_args(rename_args, n_rename_args);
                            free(buf);
                            free(footer);
                            return 2;
                        }
                        last_rc = 0;
                    } else {
                        last_rc = 1;
                    }
                    free_split_args(rename_args, n_rename_args);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        if (is_command(line, ".list")) {
            char *effective = make_effective_source(buf ? buf : "", footer);
            if (!effective) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            list_source(effective);
            free(effective);
            continue;
        }

        if (is_command(line, ".decl")) {
            char *effective = make_effective_source(buf ? buf : "", footer);
            if (!effective) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            list_declarations(effective);
            free(effective);
            continue;
        }

        {
            char *var_names[OFORT_MAX_PARAMS];
            int n_var_names = 0;
            int parsed = repl_named_command_args(line, ".vars", var_names, &n_var_names);
            if (parsed != 0) {
                if (parsed > 0) {
                    char vars_buf[OFORT_MAX_OUTPUT];
                    last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
                    if (last_rc == 0) {
                        if (ofort_dump_variables(repl_interp, (const char *const *)var_names,
                                                 n_var_names, vars_buf, sizeof(vars_buf)) == 0 &&
                            n_var_names == 0) {
                            fputs("(no variables)\n", stdout);
                        } else {
                            fputs(vars_buf, stdout);
                        }
                    }
                    free_split_args(var_names, n_var_names);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *var_names[OFORT_MAX_PARAMS];
            int n_var_names = 0;
            int parsed = repl_named_command_args(line, ".info", var_names, &n_var_names);
            if (parsed != 0) {
                if (parsed > 0) {
                    char vars_buf[OFORT_MAX_OUTPUT];
                    last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
                    if (last_rc == 0) {
                        if (ofort_dump_variable_info(repl_interp, (const char *const *)var_names,
                                                     n_var_names, vars_buf, sizeof(vars_buf)) == 0 &&
                            n_var_names == 0) {
                            fputs("(no variables)\n", stdout);
                        } else {
                            fputs(vars_buf, stdout);
                        }
                    }
                    free_split_args(var_names, n_var_names);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *var_names[OFORT_MAX_PARAMS];
            int n_var_names = 0;
            int parsed = repl_named_command_args(line, ".shapes", var_names, &n_var_names);
            if (parsed != 0) {
                if (parsed > 0) {
                    char shapes_buf[OFORT_MAX_OUTPUT];
                    last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
                    if (last_rc == 0) {
                        if (ofort_dump_variable_shapes(repl_interp, (const char *const *)var_names,
                                                       n_var_names, shapes_buf, sizeof(shapes_buf)) == 0 &&
                            n_var_names == 0) {
                            fputs("(no arrays)\n", stdout);
                        } else {
                            fputs(shapes_buf, stdout);
                        }
                    }
                    free_split_args(var_names, n_var_names);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *var_names[OFORT_MAX_PARAMS];
            int n_var_names = 0;
            int parsed = repl_named_command_args(line, ".sizes", var_names, &n_var_names);
            if (parsed != 0) {
                if (parsed > 0) {
                    char sizes_buf[OFORT_MAX_OUTPUT];
                    last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
                    if (last_rc == 0) {
                        if (ofort_dump_variable_sizes(repl_interp, (const char *const *)var_names,
                                                      n_var_names, sizes_buf, sizeof(sizes_buf)) == 0 &&
                            n_var_names == 0) {
                            fputs("(no arrays)\n", stdout);
                        } else {
                            fputs(sizes_buf, stdout);
                        }
                    }
                    free_split_args(var_names, n_var_names);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char *var_names[OFORT_MAX_PARAMS];
            int n_var_names = 0;
            int parsed = repl_named_command_args(line, ".stats", var_names, &n_var_names);
            if (parsed != 0) {
                if (parsed > 0) {
                    char stats_buf[OFORT_MAX_OUTPUT];
                    last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
                    if (last_rc == 0) {
                        if (ofort_dump_variable_stats(repl_interp, (const char *const *)var_names,
                                                      n_var_names, stats_buf, sizeof(stats_buf)) == 0 &&
                            n_var_names == 0) {
                            fputs("(no numeric arrays)\n", stdout);
                        } else {
                            fputs(stats_buf, stdout);
                        }
                    }
                    free_split_args(var_names, n_var_names);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            const char *path = load_run_command_path(line);
            if (path) {
                char local_path[4096];
                snprintf(local_path, sizeof(local_path), "%s", path);
                trim_line_end(local_path);
                if (load_interactive_file(local_path, &buf, &len, &cap, &footer)) {
                    ofort_destroy(repl_interp);
                    repl_interp = create_ofort_interpreter();
                    if (!repl_interp) {
                        fprintf(stderr, "failed to create Fortran interpreter\n");
                        free(buf);
                        free(footer);
                        return 2;
                    }
                    char *effective = make_effective_source(buf ? buf : "", footer);
                    if (!effective) {
                        free(buf);
                        free(footer);
                        ofort_destroy(repl_interp);
                        return 2;
                    }
                    last_rc = execute_source_text_on_interpreter(repl_interp, effective, 1, 0, 0, NULL);
                    free(effective);
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
                    repl_interp = create_ofort_interpreter();
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

        {
            char save_name[256];
            if (g_warnings_enabled &&
                source_inside_procedure(buf ? buf : "") &&
                repl_line_has_implicit_save(line, save_name, sizeof(save_name))) {
                fprintf(stderr,
                        "warning: local variable '%s' has implicit SAVE due to initialization\n",
                        save_name);
            }
        }

        {
            int line_indent = source_indent_level(buf ? buf : "");
            if (repl_line_pre_dedent(line) && line_indent > 0) {
                line_indent--;
            }
            if (!append_indented_repl_line(&buf, &len, &cap, line, line_indent)) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
        }
    }

    if (buf && buf[0] != '\0') {
        char *effective = make_effective_source(buf, footer);
        if (!effective) {
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return 2;
        }
        last_rc = execute_source_text_on_interpreter(repl_interp, effective, 1, 0, 0, NULL);
        free(effective);
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

static char *read_files_concatenated(const char *const *paths, int npaths) {
    char *source = NULL;
    size_t len = 0;
    size_t cap = 0;

    for (int i = 0; i < npaths; i++) {
        char *part = read_file(paths[i]);
        if (!part) {
            free(source);
            return NULL;
        }
        if (!append_text(&source, &len, &cap, part)) {
            free(part);
            free(source);
            return NULL;
        }
        free(part);
        if (len > 0 && source[len - 1] != '\n' && !append_text(&source, &len, &cap, "\n")) {
            free(source);
            return NULL;
        }
    }

    if (!source && !append_text(&source, &len, &cap, "")) {
        return NULL;
    }
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
    fprintf(stderr, "usage: %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing] [file1.f90 [file2.f90 ...]] [-- args...]\n", program);
    fprintf(stderr, "       %s --each [--check] [options] file-or-glob [file-or-glob ...] [-- args...]\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing] --load file.f90\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing] --load-run file.f90\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing] --check file.f90\n", program);
    fprintf(stderr, "       %s --check-gfortran file.f90\n", program);
    fprintf(stderr, "       %s < file.f90\n", program);
    fprintf(stderr, "       -w suppresses warnings\n");
    fprintf(stderr, "       --fast enables safe interpreter fast paths and suppresses warnings\n");
    fprintf(stderr, "       --no-specialize disables specialized pattern/program fast paths\n");
    fprintf(stderr, "       --time prints elapsed time for the requested operation\n");
    fprintf(stderr, "       --time-detail prints setup, lex, parse, register, execute, and total times\n");
    fprintf(stderr, "       --profile-lines prints elapsed execution time by source line\n");
    fprintf(stderr, "       --each treats each file or Windows glob match as a separate program\n");
    fprintf(stderr, "       --implicit-typing, --legacy-implicit enables historical I-N integer/rest real implicit typing\n");
    fprintf(stderr, "       with no file in a console, start an interactive session\n");
}

int main(int argc, char **argv) {
    char *source;
    PathList source_paths = {0};
    const char *load_path = NULL;
    const char *syntax_check_path = NULL;
    const char *check_path = NULL;
    char **program_args = NULL;
    int program_argc = 0;
    int run_after_load = 0;
    int time_operation = 0;
    int each_mode = 0;
    int each_check = 0;
    double setup_start = 0.0;
    int i;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--each") == 0) {
            each_mode = 1;
            break;
        }
    }

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--implicit-typing") == 0 || strcmp(argv[i], "--legacy-implicit") == 0) {
            g_implicit_typing = 1;
        } else if (strcmp(argv[i], "-w") == 0) {
            g_warnings_enabled = 0;
        } else if (strcmp(argv[i], "--fast") == 0) {
            g_fast_mode = 1;
            g_warnings_enabled = 0;
        } else if (strcmp(argv[i], "--no-specialize") == 0) {
            g_specialized_fast_paths = 0;
        } else if (strcmp(argv[i], "--time") == 0) {
            time_operation = 1;
        } else if (strcmp(argv[i], "--time-detail") == 0) {
            time_operation = 1;
            g_time_detail = 1;
        } else if (strcmp(argv[i], "--profile-lines") == 0) {
            g_line_profile = 1;
        } else if (strcmp(argv[i], "--each") == 0) {
            each_mode = 1;
        } else if (strcmp(argv[i], "--") == 0) {
            program_args = &argv[i + 1];
            program_argc = argc - i - 1;
            break;
        } else if (each_mode && strcmp(argv[i], "--check") == 0) {
            each_check = 1;
        } else if (strcmp(argv[i], "--load") == 0 ||
                   strcmp(argv[i], "--load-run") == 0 ||
                   (!each_mode && strcmp(argv[i], "--check") == 0) ||
                   strcmp(argv[i], "--check-gfortran") == 0) {
            const char *opt = argv[i];
            if (++i >= argc) {
                print_usage(argv[0]);
                path_list_free(&source_paths);
                return 2;
            }
            if (each_mode || load_path || syntax_check_path || check_path || source_paths.count > 0) {
                print_usage(argv[0]);
                path_list_free(&source_paths);
                return 2;
            }
            if (strcmp(opt, "--load") == 0) {
                load_path = argv[i];
            } else if (strcmp(opt, "--load-run") == 0) {
                load_path = argv[i];
                run_after_load = 1;
            } else if (strcmp(opt, "--check") == 0) {
                syntax_check_path = argv[i];
            } else {
                check_path = argv[i];
            }
        } else if (argv[i][0] == '-') {
            print_usage(argv[0]);
            path_list_free(&source_paths);
            return 2;
        } else {
            if (load_path || syntax_check_path || check_path) {
                print_usage(argv[0]);
                path_list_free(&source_paths);
                return 2;
            }
            if (each_mode) {
                if (!expand_windows_glob(&source_paths, argv[i])) {
                    path_list_free(&source_paths);
                    return 2;
                }
            } else if (!path_list_add(&source_paths, argv[i])) {
                path_list_free(&source_paths);
                return 2;
            }
        }
    }

    if (check_path) {
        double start = monotonic_seconds();
        int rc = check_with_gfortran(check_path);
        if (time_operation) print_elapsed_time(start);
        path_list_free(&source_paths);
        return rc;
    }

    if (syntax_check_path) {
        double start = monotonic_seconds();
        int rc = check_ofort_file(syntax_check_path);
        if (time_operation && !g_time_detail) print_elapsed_time(start);
        path_list_free(&source_paths);
        return rc;
    }

    if (load_path) {
        double start = monotonic_seconds();
        int rc = run_interactive(load_path, run_after_load);
        if (time_operation) print_elapsed_time(start);
        path_list_free(&source_paths);
        return rc;
    }

    if (each_mode) {
        int rc;
        if (source_paths.count == 0) {
            print_usage(argv[0]);
            path_list_free(&source_paths);
            return 2;
        }
        rc = run_each_file(source_paths.items, source_paths.count, each_check,
                           program_argc, program_args, time_operation);
        path_list_free(&source_paths);
        return rc;
    }

    if (source_paths.count > 0) {
        setup_start = monotonic_seconds();
        source = read_files_concatenated(source_paths.items, source_paths.count);
    } else if (ISATTY(FILENO(stdin))) {
        path_list_free(&source_paths);
        return run_interactive(NULL, 0);
    } else {
        setup_start = monotonic_seconds();
        source = read_stream(stdin, "stdin");
    }
    if (!source) {
        path_list_free(&source_paths);
        return 2;
    }
    {
        double start = setup_start > 0.0 ? setup_start : monotonic_seconds();
        int rc = execute_source_text(source, 0, 0, program_argc, program_args, start);
        if (time_operation && !g_time_detail) print_elapsed_time(start);
        free(source);
        path_list_free(&source_paths);
        return rc;
    }
}
