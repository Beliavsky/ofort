#include "ofort.h"
#include "ofort_fixed_form.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>
#include <math.h>
#include <stdint.h>
#include <sys/stat.h>

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
static char *read_source_file(const char *path);
static char *copy_string(const char *text);
static const char *skip_space(const char *line);
static int starts_with_word_nocase(const char *line, const char *word);
static int string_eq_nocase(const char *a, const char *b);
static int identifier_char(int c);
static int line_is_terminal_end(const char *start, const char *end);
static int validate_source_file_terminal_end(const char *path, const char *source);
static int has_program_unit_header(const char *source);
static int add_repl_line_to_buffer(char **buf, size_t *len, size_t *cap, const char *line);
static int source_defines_name(const char *source, const char *name);
static int source_line_count(const char *source);
static int insert_source_line(char **buf, size_t *len, size_t *cap, int line_no, const char *text);
static int replace_source_line(char **buf, size_t *len, size_t *cap, int line_no, const char *text);
static const char *source_line_start(const char *source, int line_no);
static int repl_named_command_args(const char *line, const char *command, char **args, int *nargs);

static char g_repl_prompt[128] = "> ";

typedef struct {
    const char **items;
    int count;
    int cap;
} PathList;

typedef struct {
    char *path;
    int start_line;
    int line_count;
} SourceMapEntry;

typedef struct {
    SourceMapEntry *entries;
    int count;
    int cap;
} SourceMap;

typedef enum {
    SOURCE_FORM_AUTO = 0,
    SOURCE_FORM_FREE,
    SOURCE_FORM_FIXED
} SourceFormMode;

static SourceFormMode g_source_form = SOURCE_FORM_AUTO;
static int g_save_free_form = 0;
static int g_quiet = 0;
static int g_repl_auto_end = 0;

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

static void source_map_free(SourceMap *map) {
    if (!map) return;
    for (int i = 0; i < map->count; i++) {
        free(map->entries[i].path);
    }
    free(map->entries);
    map->entries = NULL;
    map->count = 0;
    map->cap = 0;
}

static int source_map_add(SourceMap *map, const char *path, int start_line, int line_count) {
    SourceMapEntry *new_entries;

    if (!map) return 1;
    if (map->count == map->cap) {
        int new_cap = map->cap ? map->cap * 2 : 8;
        new_entries = (SourceMapEntry *)realloc(map->entries, (size_t)new_cap * sizeof(*map->entries));
        if (!new_entries) {
            fprintf(stderr, "out of memory\n");
            return 0;
        }
        map->entries = new_entries;
        map->cap = new_cap;
    }
    map->entries[map->count].path = copy_string(path);
    if (!map->entries[map->count].path) {
        fprintf(stderr, "out of memory\n");
        return 0;
    }
    map->entries[map->count].start_line = start_line;
    map->entries[map->count].line_count = line_count;
    map->count++;
    return 1;
}

static int source_text_line_count(const char *text) {
    int lines = 0;
    const char *p;

    if (!text || text[0] == '\0') return 0;
    lines = 1;
    for (p = text; *p; p++) {
        if (*p == '\n' && p[1] != '\0') {
            lines++;
        }
    }
    return lines;
}

static const SourceMapEntry *source_map_find(const SourceMap *map, int global_line, int *local_line) {
    if (!map || global_line <= 0) return NULL;
    for (int i = 0; i < map->count; i++) {
        const SourceMapEntry *entry = &map->entries[i];
        int start = entry->start_line;
        int end = start + entry->line_count - 1;
        if (entry->line_count > 0 && global_line >= start && global_line <= end) {
            if (local_line) *local_line = global_line - start + 1;
            return entry;
        }
    }
    return NULL;
}

static int extract_error_line(const char *error) {
    const char *p;

    if (!error) return 0;
    p = strstr(error, " at line ");
    if (p) return atoi(p + 9);
    p = strstr(error, "\nline ");
    if (p) return atoi(p + 6);
    if (strncmp(error, "line ", 5) == 0) return atoi(error + 5);
    return 0;
}

static void print_source_mapped_error(const char *error, const SourceMap *map) {
    int global_line = extract_error_line(error);
    int local_line = 0;
    const SourceMapEntry *entry = source_map_find(map, global_line, &local_line);

    if (entry) {
        fprintf(stderr, "%s:%d: ", entry->path, local_line);
    }
    fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
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

static int set_repl_prompt_from_command(const char *line) {
    const char *p;
    const char *end;
    size_t len;
    if (!command_starts_with(line, ".prompt")) return 0;
    p = line + strlen(".prompt");
    while (*p && isspace((unsigned char)*p)) p++;
    end = p + strlen(p);
    while (end > p && (end[-1] == '\n' || end[-1] == '\r' || isspace((unsigned char)end[-1]))) end--;
    if (end == p) {
        snprintf(g_repl_prompt, sizeof(g_repl_prompt), "%s", "> ");
        return 1;
    }
    if (end - p >= 2 && ((*p == '"' && end[-1] == '"') || (*p == '\'' && end[-1] == '\''))) {
        p++;
        end--;
    }
    len = (size_t)(end - p);
    if (len >= sizeof(g_repl_prompt)) len = sizeof(g_repl_prompt) - 1;
    memcpy(g_repl_prompt, p, len);
    g_repl_prompt[len] = '\0';
    return 1;
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

static void list_source_plain(const char *source) {
    if (source && *source) {
        fputs(source, stdout);
        if (source[strlen(source) - 1] != '\n') {
            fputc('\n', stdout);
        }
    }
}

typedef struct {
    char prefix[64];
    char names[1024];
    int used;
} ReplDeclGroup;

static int simple_decl_prefix_allowed(const char *prefix) {
    return string_eq_nocase(prefix, "integer") ||
           string_eq_nocase(prefix, "logical") ||
           string_eq_nocase(prefix, "real") ||
           string_eq_nocase(prefix, "double precision") ||
           string_eq_nocase(prefix, "complex");
}

static void trim_span(const char **start, const char **end) {
    while (*start < *end && isspace((unsigned char)**start)) (*start)++;
    while (*end > *start && isspace((unsigned char)(*end)[-1])) (*end)--;
}

static int parse_simple_groupable_decl(const char *line, size_t line_len,
                                       char *prefix, size_t prefix_size,
                                       char *name, size_t name_size) {
    const char *start = line;
    const char *end = line + line_len;
    const char *dc;
    const char *ps;
    const char *pe;
    const char *ns;
    const char *ne;
    size_t len;

    trim_span(&start, &end);
    if (start >= end || *start == '!') return 0;
    dc = strstr(start, "::");
    if (!dc || dc >= end) return 0;

    ps = start;
    pe = dc;
    trim_span(&ps, &pe);
    len = (size_t)(pe - ps);
    if (len == 0 || len >= prefix_size) return 0;
    for (const char *p = ps; p < pe; p++) {
        if (*p == ',' || *p == '(' || *p == ')' || *p == '=') return 0;
    }
    memcpy(prefix, ps, len);
    prefix[len] = '\0';
    if (!simple_decl_prefix_allowed(prefix)) return 0;

    ns = dc + 2;
    ne = end;
    trim_span(&ns, &ne);
    if (ns >= ne || !(isalpha((unsigned char)*ns) || *ns == '_')) return 0;
    for (const char *p = ns; p < ne; p++) {
        if (!identifier_char((unsigned char)*p)) return 0;
    }
    len = (size_t)(ne - ns);
    if (len == 0 || len >= name_size) return 0;
    memcpy(name, ns, len);
    name[len] = '\0';
    return 1;
}

static int parse_simple_decl_names(const char *line, size_t line_len,
                                   char *prefix, size_t prefix_size,
                                   char names[][256], int *n_names) {
    const char *start = line;
    const char *end = line + line_len;
    const char *dc;
    const char *ps;
    const char *pe;
    const char *p;
    size_t len;

    *n_names = 0;
    trim_span(&start, &end);
    if (start >= end || *start == '!') return 0;
    dc = strstr(start, "::");
    if (!dc || dc >= end) return 0;

    ps = start;
    pe = dc;
    trim_span(&ps, &pe);
    len = (size_t)(pe - ps);
    if (len == 0 || len >= prefix_size) return 0;
    for (const char *q = ps; q < pe; q++) {
        if (*q == ',' || *q == '(' || *q == ')' || *q == '=') return 0;
    }
    memcpy(prefix, ps, len);
    prefix[len] = '\0';
    if (!simple_decl_prefix_allowed(prefix)) return 0;

    p = dc + 2;
    while (p < end) {
        const char *ns = p;
        const char *ne;
        trim_span(&ns, &end);
        if (ns >= end) return 0;
        ne = ns;
        while (ne < end && *ne != ',') ne++;
        p = ne < end ? ne + 1 : ne;
        trim_span(&ns, &ne);
        if (ns >= ne || !(isalpha((unsigned char)*ns) || *ns == '_')) return 0;
        for (const char *q = ns; q < ne; q++) {
            if (!identifier_char((unsigned char)*q)) return 0;
        }
        len = (size_t)(ne - ns);
        if (len == 0 || len >= 256 || *n_names >= OFORT_MAX_PARAMS) return 0;
        memcpy(names[*n_names], ns, len);
        names[*n_names][len] = '\0';
        (*n_names)++;
    }
    return *n_names > 0;
}

static int source_line_uses_name(const char *line, size_t line_len, const char *name) {
    const char *p = line;
    const char *end = line + line_len;
    size_t name_len = strlen(name);

    while (p < end) {
        if (*p == '!') {
            break;
        }
        if (*p == '\'' || *p == '"') {
            char quote = *p++;
            while (p < end) {
                if (*p == quote) {
                    if (p + 1 < end && p[1] == quote) {
                        p += 2;
                        continue;
                    }
                    p++;
                    break;
                }
                p++;
            }
            continue;
        }
        if (isalpha((unsigned char)*p) || *p == '_') {
            const char *tok = p;
            size_t tok_len;
            while (p < end && identifier_char((unsigned char)*p)) p++;
            tok_len = (size_t)(p - tok);
            if (tok_len == name_len) {
                int same = 1;
                for (size_t i = 0; i < name_len; i++) {
                    if (tolower((unsigned char)tok[i]) != tolower((unsigned char)name[i])) {
                        same = 0;
                        break;
                    }
                }
                if (same) return 1;
            }
            continue;
        }
        p++;
    }
    return 0;
}

static int source_uses_name_outside_line(const char *source, int skip_line_no, const char *name) {
    const char *line = source;
    int line_no = 1;

    while (*line) {
        const char *end = strchr(line, '\n');
        size_t line_len = end ? (size_t)(end - line) : strlen(line);
        if (line_no != skip_line_no && source_line_uses_name(line, line_len, name)) {
            return 1;
        }
        line = end ? end + 1 : line + line_len;
        line_no++;
    }
    return 0;
}

static int name_in_command_args(const char *name, char **args, int nargs) {
    for (int i = 0; i < nargs; i++) {
        if (string_eq_nocase(name, args[i])) return 1;
    }
    return 0;
}

static int list_unused_declarations_in_source(const char *source) {
    const char *line = source ? source : "";
    int line_no = 1;
    int n_unused = 0;

    while (*line) {
        const char *end = strchr(line, '\n');
        size_t line_len = end ? (size_t)(end - line) : strlen(line);
        char prefix[64];
        char names[OFORT_MAX_PARAMS][256];
        int n_names = 0;
        if (parse_simple_decl_names(line, line_len, prefix, sizeof(prefix), names, &n_names)) {
            for (int i = 0; i < n_names; i++) {
                if (!source_uses_name_outside_line(source, line_no, names[i])) {
                    if (n_unused == 0) fputs("unused declarations:\n", stdout);
                    printf("  %s\n", names[i]);
                    n_unused++;
                }
            }
        }
        line = end ? end + 1 : line + line_len;
        line_no++;
    }
    if (n_unused == 0) {
        fputs("unused declarations: (none)\n", stdout);
    }
    return n_unused;
}

static int rewrite_declarations_remove_names(char **buf, size_t *len, size_t *cap,
                                             char **remove_names, int n_remove_names,
                                             int remove_unused) {
    const char *source = *buf ? *buf : "";
    const char *line = source;
    char *out = NULL;
    size_t out_len = 0;
    size_t out_cap = 0;
    int line_no = 1;

    while (*line) {
        const char *end = strchr(line, '\n');
        size_t line_len = end ? (size_t)(end - line) : strlen(line);
        char prefix[64];
        char names[OFORT_MAX_PARAMS][256];
        int n_names = 0;
        if (parse_simple_decl_names(line, line_len, prefix, sizeof(prefix), names, &n_names)) {
            char rebuilt[4096];
            size_t rebuilt_len = 0;
            int kept = 0;
            int overflow = 0;
            rebuilt[0] = '\0';
            for (int i = 0; i < n_names; i++) {
                int remove = remove_unused ?
                    !source_uses_name_outside_line(source, line_no, names[i]) :
                    name_in_command_args(names[i], remove_names, n_remove_names);
                if (remove) continue;
                if (kept == 0) {
                    int n = snprintf(rebuilt, sizeof(rebuilt), "%s :: %s", prefix, names[i]);
                    if (n < 0 || (size_t)n >= sizeof(rebuilt)) overflow = 1;
                    else rebuilt_len = (size_t)n;
                } else {
                    int n = snprintf(rebuilt + rebuilt_len, sizeof(rebuilt) - rebuilt_len,
                                     ", %s", names[i]);
                    if (n < 0 || (size_t)n >= sizeof(rebuilt) - rebuilt_len) overflow = 1;
                    else rebuilt_len += (size_t)n;
                }
                kept++;
            }
            if (overflow) {
                free(out);
                return 0;
            }
            if (kept > 0) {
                if (!append_text(&out, &out_len, &out_cap, rebuilt) ||
                    (end && !append_text(&out, &out_len, &out_cap, "\n"))) {
                    free(out);
                    return 0;
                }
            }
        } else {
            if (!append_text_n(&out, &out_len, &out_cap, line, line_len) ||
                (end && !append_text(&out, &out_len, &out_cap, "\n"))) {
                free(out);
                return 0;
            }
        }
        line = end ? end + 1 : line + line_len;
        line_no++;
    }

    free(*buf);
    *buf = out;
    *len = out_len;
    *cap = out_cap;
    return 1;
}

static int flush_decl_groups(char **out, size_t *out_len, size_t *out_cap,
                             ReplDeclGroup *groups, int *n_groups) {
    char line[1400];
    for (int i = 0; i < *n_groups; i++) {
        if (!groups[i].used) continue;
        snprintf(line, sizeof(line), "%s :: %s\n", groups[i].prefix, groups[i].names);
        if (!append_text(out, out_len, out_cap, line)) return 0;
        groups[i].used = 0;
    }
    *n_groups = 0;
    return 1;
}

static int group_declarations_in_source(char **buf, size_t *len, size_t *cap) {
    const char *source = *buf ? *buf : "";
    const char *line = source;
    char *out = NULL;
    size_t out_len = 0;
    size_t out_cap = 0;
    ReplDeclGroup groups[16];
    int n_groups = 0;
    memset(groups, 0, sizeof(groups));

    while (*line) {
        const char *end = strchr(line, '\n');
        size_t line_len = end ? (size_t)(end - line) : strlen(line);
        char prefix[64];
        char name[256];
        if (parse_simple_groupable_decl(line, line_len, prefix, sizeof(prefix), name, sizeof(name))) {
            int gi = -1;
            for (int i = 0; i < n_groups; i++) {
                if (string_eq_nocase(groups[i].prefix, prefix)) {
                    gi = i;
                    break;
                }
            }
            if (gi < 0) {
                if (n_groups >= (int)(sizeof(groups) / sizeof(groups[0]))) {
                    if (!flush_decl_groups(&out, &out_len, &out_cap, groups, &n_groups)) {
                        free(out);
                        return 0;
                    }
                }
                gi = n_groups++;
                snprintf(groups[gi].prefix, sizeof(groups[gi].prefix), "%s", prefix);
                groups[gi].names[0] = '\0';
                groups[gi].used = 1;
            }
            if (groups[gi].names[0]) {
                if (strlen(groups[gi].names) + strlen(name) + 3 >= sizeof(groups[gi].names)) {
                    free(out);
                    return 0;
                }
                strcat(groups[gi].names, ", ");
            }
            strcat(groups[gi].names, name);
        } else {
            if (!flush_decl_groups(&out, &out_len, &out_cap, groups, &n_groups) ||
                !append_text_n(&out, &out_len, &out_cap, line, line_len) ||
                (end && !append_text(&out, &out_len, &out_cap, "\n"))) {
                free(out);
                return 0;
            }
        }
        line = end ? end + 1 : line + line_len;
    }
    if (!flush_decl_groups(&out, &out_len, &out_cap, groups, &n_groups)) {
        free(out);
        return 0;
    }
    free(*buf);
    *buf = out;
    *len = out_len;
    *cap = out_cap;
    return 1;
}

static int file_exists(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        return 0;
    }
    fclose(fp);
    return 1;
}

static int source_has_implicit_statement(const char *source) {
    const char *line = source;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        const char *p;

        if (len >= sizeof(local)) len = sizeof(local) - 1;
        memcpy(local, line, len);
        local[len] = '\0';
        p = skip_space(local);
        if (starts_with_word_nocase(p, "implicit")) return 1;
        line = end ? end + 1 : NULL;
    }
    return 0;
}

static int line_is_program_unit_header_repl(const char *p) {
    p = skip_space(p);
    if (starts_with_word_nocase(p, "program") ||
        starts_with_word_nocase(p, "module") ||
        starts_with_word_nocase(p, "submodule") ||
        starts_with_word_nocase(p, "subroutine") ||
        starts_with_word_nocase(p, "function") ||
        starts_with_word_nocase(p, "block data")) {
        return 1;
    }
    if (starts_with_word_nocase(p, "pure")) {
        p = skip_space(p + 4);
        return starts_with_word_nocase(p, "subroutine") ||
               starts_with_word_nocase(p, "function");
    }
    if (starts_with_word_nocase(p, "elemental")) {
        p = skip_space(p + 9);
        return starts_with_word_nocase(p, "subroutine") ||
               starts_with_word_nocase(p, "function");
    }
    if (starts_with_word_nocase(p, "recursive")) {
        p = skip_space(p + 9);
        return starts_with_word_nocase(p, "subroutine") ||
               starts_with_word_nocase(p, "function");
    }
    return 0;
}

static int append_source_with_repl_implicit_none(char **out, size_t *len, size_t *cap,
                                                const char *source) {
    const char *line = source ? source : "";
    int inserted = 0;
    int saw_header = 0;

    if (!source || source[0] == '\0') {
        return append_text(out, len, cap, "implicit none\n");
    }
    if (source_has_implicit_statement(source)) {
        return append_text(out, len, cap, source);
    }

    while (line && *line) {
        const char *end = strchr(line, '\n');
        size_t line_len = end ? (size_t)(end - line + 1) : strlen(line);
        char local[4096];
        size_t copy_len = line_len;
        const char *p;

        if (copy_len > 0 && (line[copy_len - 1] == '\n' || line[copy_len - 1] == '\r')) copy_len--;
        if (copy_len > 0 && line[copy_len - 1] == '\r') copy_len--;
        if (copy_len >= sizeof(local)) copy_len = sizeof(local) - 1;
        memcpy(local, line, copy_len);
        local[copy_len] = '\0';
        p = skip_space(local);

        if (*p == '\0' || *p == '!') {
            if (!append_text_n(out, len, cap, line, line_len)) return 0;
            line = end ? end + 1 : NULL;
            continue;
        }

        if (!saw_header && line_is_program_unit_header_repl(p)) {
            saw_header = 1;
            if (!append_text_n(out, len, cap, line, line_len)) return 0;
            line = end ? end + 1 : NULL;
            continue;
        }

        if (starts_with_word_nocase(p, "use")) {
            if (!append_text_n(out, len, cap, line, line_len)) return 0;
            line = end ? end + 1 : NULL;
            continue;
        }

        if (!append_text(out, len, cap, "implicit none\n")) return 0;
        inserted = 1;
        break;
    }

    if (!inserted) {
        if (!append_text(out, len, cap, "implicit none\n")) return 0;
    }
    if (line && *line) {
        if (!append_text(out, len, cap, line)) return 0;
    }
    return 1;
}

static int append_effective_source(char **out, size_t *len, size_t *cap,
                                   const char *source, const char *footer) {
    if (!append_source_with_repl_implicit_none(out, len, cap, source ? source : "")) {
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

static int save_interactive_source_to_path(const char *source, const char *footer,
                                           const char *path, int overwrite) {
    char *effective;
    FILE *fp;

    if (!source || source[0] == '\0') {
        return 0;
    }
    if (!overwrite && file_exists(path)) {
        fprintf(stderr, "%s already exists; use --overwrite to replace it\n", path);
        return 1;
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

static int save_interactive_source(const char *source, const char *footer) {
    char path[64];
    int i;

    if (!source || source[0] == '\0') {
        return 0;
    }
    strcpy(path, "main.f90");
    for (i = 1; file_exists(path); i++) {
        snprintf(path, sizeof(path), "main%d.f90", i);
    }
    return save_interactive_source_to_path(source, footer, path, 0);
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

static void build_indented_repl_line(char *indented, size_t indented_size,
                                     const char *line, int indent_level) {
    const char *text = skip_space(line);
    size_t text_len = strlen(text);
    size_t pos = 0;

    if (!indented || indented_size == 0) return;
    if (indent_level < 0) {
        indent_level = 0;
    }
    for (int i = 0; i < indent_level * 2 && pos + 1 < indented_size; i++) {
        indented[pos++] = ' ';
    }
    if (text_len > indented_size - pos - 1) {
        text_len = indented_size - pos - 1;
    }
    memcpy(indented + pos, text, text_len);
    pos += text_len;
    indented[pos] = '\0';
}

static int insert_indented_repl_line(char **buf, size_t *len, size_t *cap,
                                     int line_no, const char *line, int indent_level) {
    char indented[8192];

    build_indented_repl_line(indented, sizeof(indented), line, indent_level);
    if (line_no == source_line_count(*buf ? *buf : "") + 1) {
        return add_repl_line_to_buffer(buf, len, cap, indented);
    }
    return insert_source_line(buf, len, cap, line_no, indented);
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

static char *source_prefix_before_line(const char *source, int line_no) {
    const char *start = source ? source : "";
    const char *pos = source_line_start(start, line_no);
    size_t n;
    char *prefix;

    if (!pos) pos = start + strlen(start);
    n = (size_t)(pos - start);
    prefix = (char *)malloc(n + 1);
    if (!prefix) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }
    memcpy(prefix, start, n);
    prefix[n] = '\0';
    return prefix;
}

static void trim_trailing_space(char *text) {
    size_t n;

    if (!text) return;
    n = strlen(text);
    while (n > 0 && isspace((unsigned char)text[n - 1])) {
        text[--n] = '\0';
    }
}

static int line_matches_auto_end(const char *line, const char *end_line) {
    char lower[4096];
    char expected[128];

    lower_logical_line(lower, sizeof(lower), line);
    snprintf(expected, sizeof(expected), "%s", end_line ? end_line : "");
    for (char *p = expected; *p; p++) {
        *p = (char)tolower((unsigned char)*p);
    }
    trim_trailing_space(lower);
    trim_trailing_space(expected);
    return expected[0] != '\0' && strcmp(lower, expected) == 0;
}

static int name_after_word_lower(const char *lower, const char *word, char *name, size_t name_size) {
    const char *p = lower;
    size_t word_len = strlen(word);

    if (!name || name_size == 0) return 0;
    name[0] = '\0';
    while ((p = strstr(p, word)) != NULL) {
        int before_ok = (p == lower) || !identifier_char((unsigned char)p[-1]);
        int after_ok = !identifier_char((unsigned char)p[word_len]);
        if (before_ok && after_ok) {
            p += word_len;
            while (*p && isspace((unsigned char)*p)) p++;
            if (isalpha((unsigned char)*p) || *p == '_') {
                size_t n = 0;
                while (identifier_char((unsigned char)p[n]) && n + 1 < name_size) {
                    name[n] = p[n];
                    n++;
                }
                name[n] = '\0';
                return n > 0;
            }
            return 0;
        }
        p += word_len;
    }
    return 0;
}

static int repl_auto_end_for_line(const char *line, char *end_line, size_t end_line_size) {
    char lower[4096];
    char name[128];
    const char *decl;

    if (!g_repl_auto_end || !line || !end_line || end_line_size == 0) return 0;
    end_line[0] = '\0';
    lower_logical_line(lower, sizeof(lower), line);
    trim_trailing_space(lower);
    if (lower[0] == '\0' || lower[0] == '!' ||
        line_starts_word_lower(lower, "end") ||
        line_starts_word_lower(lower, "else") ||
        line_starts_word_lower(lower, "case") ||
        line_starts_word_lower(lower, "contains")) {
        return 0;
    }

    if (line_starts_word_lower(lower, "program") && name_after_word_lower(lower, "program", name, sizeof(name))) {
        snprintf(end_line, end_line_size, "end program %.80s", name);
        return 1;
    }
    if (line_starts_word_lower(lower, "module") && !line_starts_word_lower(lower, "module procedure") &&
        name_after_word_lower(lower, "module", name, sizeof(name))) {
        snprintf(end_line, end_line_size, "end module %.80s", name);
        return 1;
    }
    if (name_after_word_lower(lower, "subroutine", name, sizeof(name))) {
        snprintf(end_line, end_line_size, "end subroutine %.80s", name);
        return 1;
    }
    if (name_after_word_lower(lower, "function", name, sizeof(name))) {
        snprintf(end_line, end_line_size, "end function %.80s", name);
        return 1;
    }
    if (line_starts_word_lower(lower, "if") && line_contains_word_lower(lower, "then")) {
        snprintf(end_line, end_line_size, "%s", "end if");
        return 1;
    }
    if (line_starts_word_lower(lower, "do")) {
        snprintf(end_line, end_line_size, "%s", "end do");
        return 1;
    }
    if (line_starts_word_lower(lower, "select")) {
        snprintf(end_line, end_line_size, "%s", "end select");
        return 1;
    }
    if (line_starts_word_lower(lower, "where")) {
        snprintf(end_line, end_line_size, "%s", "end where");
        return 1;
    }
    if (line_starts_word_lower(lower, "forall")) {
        snprintf(end_line, end_line_size, "%s", "end forall");
        return 1;
    }
    if (line_starts_word_lower(lower, "associate")) {
        snprintf(end_line, end_line_size, "%s", "end associate");
        return 1;
    }
    if (line_starts_word_lower(lower, "block")) {
        snprintf(end_line, end_line_size, "%s", "end block");
        return 1;
    }
    if (line_starts_word_lower(lower, "interface")) {
        snprintf(end_line, end_line_size, "%s", "end interface");
        return 1;
    }
    if (line_starts_word_lower(lower, "type") && lower[4] != '(') {
        decl = strstr(lower, "::");
        if (decl) {
            decl += 2;
            while (*decl && isspace((unsigned char)*decl)) decl++;
            if (isalpha((unsigned char)*decl) || *decl == '_') {
                size_t n = 0;
                while (identifier_char((unsigned char)decl[n]) && n + 1 < sizeof(name)) {
                    name[n] = decl[n];
                    n++;
                }
                name[n] = '\0';
                snprintf(end_line, end_line_size, "end type %.80s", name);
                return 1;
            }
        } else if (name_after_word_lower(lower, "type", name, sizeof(name))) {
            snprintf(end_line, end_line_size, "end type %.80s", name);
            return 1;
        }
    }
    return 0;
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
    if (*len == 0) {
        (*buf)[0] = '\0';
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

    if (*p == '[') {
        p++;
        while (*p == ' ' || *p == '\t') p++;
    } else if (*p == '(' && p[1] == '/') {
        p += 2;
        while (*p == ' ' || *p == '\t') p++;
    }
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

static const char *skip_repl_string_literal(const char *p, const char *end, int *literal_len) {
    char quote;
    int len = 0;

    if (!p || p >= end || (*p != '\'' && *p != '"')) return NULL;
    quote = *p++;
    while (p < end) {
        if (*p == quote) {
            if (p + 1 < end && p[1] == quote) {
                len++;
                p += 2;
                continue;
            }
            if (literal_len) *literal_len = len;
            return p + 1;
        }
        len++;
        p++;
    }
    return NULL;
}

static int rewrite_repl_character_constructor_shortcut(char *line, size_t line_size) {
    const char *start;
    const char *p;
    const char *end;
    const char *close;
    const char *tail;
    char rewritten[4096];
    int first_len = -1;
    int max_len = 0;
    int n_elems = 0;
    int mixed = 0;
    size_t prefix_len;
    size_t body_len;

    if (!line || line_size == 0) return 0;
    start = line;
    while ((start = strchr(start, '[')) != NULL) {
        int in_string = 0;
        char quote = '\0';
        const char *q;
        for (q = line; q < start; q++) {
            if (in_string) {
                if (*q == quote) {
                    if (q + 1 < start && q[1] == quote) q++;
                    else in_string = 0;
                }
            } else if (*q == '\'' || *q == '"') {
                in_string = 1;
                quote = *q;
            }
        }
        if (!in_string) break;
        start++;
    }
    if (!start) return 0;

    p = start + 1;
    end = line + strlen(line);
    while (p < end && isspace((unsigned char)*p)) p++;
    {
        const char *dc = strstr(p, "::");
        const char *rb = strchr(p, ']');
        if (!rb) return 0;
        if (dc && dc < rb) return 0;
    }

    for (;;) {
        int lit_len = 0;
        const char *after;
        while (p < end && isspace((unsigned char)*p)) p++;
        after = skip_repl_string_literal(p, end, &lit_len);
        if (!after) return 0;
        if (first_len < 0) first_len = lit_len;
        if (lit_len != first_len) mixed = 1;
        if (lit_len > max_len) max_len = lit_len;
        n_elems++;
        p = after;
        while (p < end && isspace((unsigned char)*p)) p++;
        if (*p == ',') {
            p++;
            continue;
        }
        if (*p == ']') break;
        return 0;
    }
    close = p;
    tail = close + 1;
    if (n_elems < 2 || !mixed || max_len <= 0) return 0;

    prefix_len = (size_t)(start - line);
    body_len = (size_t)(close - (start + 1));
    if (prefix_len + body_len + strlen(tail) + 48 >= sizeof(rewritten)) return 0;
    snprintf(rewritten, sizeof(rewritten), "%.*s[character(len=%d) :: %.*s]%s",
             (int)prefix_len, line, max_len, (int)body_len, start + 1, tail);
    if (strlen(rewritten) + 1 > line_size) return 0;
    strcpy(line, rewritten);
    return max_len;
}

static int parse_save_command(const char *line, const char *command,
                              char *path, size_t path_size, int *has_path,
                              int *overwrite) {
    char *args[OFORT_MAX_PARAMS];
    int nargs = 0;
    const char *p;
    int ok = 1;

    if (!command_starts_with(line, command)) return 0;
    p = skip_space(line + strlen(command));
    *has_path = 0;
    *overwrite = 0;
    if (!split_command_args(p, args, &nargs)) return -1;
    if (nargs == 0) return 1;
    if (nargs == 1) {
        if (strcmp(args[0], "--overwrite") == 0) {
            fprintf(stderr, "%s --overwrite requires a filename\n", command);
            ok = 0;
        } else {
            snprintf(path, path_size, "%s", args[0]);
            *has_path = 1;
        }
    } else if (nargs == 2 && strcmp(args[1], "--overwrite") == 0) {
        snprintf(path, path_size, "%s", args[0]);
        *has_path = 1;
        *overwrite = 1;
    } else {
        fprintf(stderr, "usage: %s [file] [--overwrite]\n", command);
        ok = 0;
    }
    free_split_args(args, nargs);
    return ok ? 1 : -1;
}

static int copy_repl_shortcut_identifier(const char **p_in, char *name, size_t name_size) {
    const char *p = *p_in;
    const char *start;
    size_t len;

    if (!(isalpha((unsigned char)*p) || *p == '_')) return 0;
    start = p;
    p++;
    while (identifier_char((unsigned char)*p)) p++;
    len = (size_t)(p - start);
    if (len == 0 || len >= name_size) return 0;
    memcpy(name, start, len);
    name[len] = '\0';
    *p_in = p;
    return 1;
}

static int character_literal_length(const char *rhs) {
    const char *p = skip_space(rhs);
    char quote;
    int len = 0;

    if (*p != '"' && *p != '\'') return -1;
    quote = *p++;
    while (*p) {
        if (*p == quote) {
            if (p[1] == quote) {
                len++;
                p += 2;
                continue;
            }
            return len;
        }
        if (*p == '\r' || *p == '\n') return -1;
        len++;
        p++;
    }
    return -1;
}

static int repl_shortcut_decl_type(const char *rhs, char *decl, size_t decl_size) {
    ReplType type = literal_rhs_type(rhs);
    const char *p = skip_space(rhs);

    switch (type) {
        case REPL_TYPE_INTEGER:
            snprintf(decl, decl_size, "integer");
            return 1;
        case REPL_TYPE_REAL:
            snprintf(decl, decl_size, "real");
            return 1;
        case REPL_TYPE_DOUBLE:
            snprintf(decl, decl_size, "double precision");
            return 1;
        case REPL_TYPE_LOGICAL:
            snprintf(decl, decl_size, "logical");
            return 1;
        case REPL_TYPE_CHARACTER: {
            int len = character_literal_length(rhs);
            if (len < 0) return 0;
            snprintf(decl, decl_size, "character(len=%d)", len);
            return 1;
        }
        default:
            break;
    }

    if (starts_with_word_nocase(p, "kind")) {
        const char *q = p + 4;
        while (*q == ' ' || *q == '\t') q++;
        if (*q == '(') {
            snprintf(decl, decl_size, "integer");
            return 1;
        }
    }

    return 0;
}

static int line_is_parameter_declaration_for_name(const char *line, const char *name) {
    const char *p = skip_space(line);
    const char *dc;
    const char *q;

    if (!(starts_with_word_nocase(p, "integer") ||
          starts_with_word_nocase(p, "real") ||
          starts_with_word_nocase(p, "double") ||
          starts_with_word_nocase(p, "character") ||
          starts_with_word_nocase(p, "logical") ||
          starts_with_word_nocase(p, "complex"))) {
        return 0;
    }
    dc = strstr(p, "::");
    if (!dc || !declaration_line_has_name(p, name)) return 0;
    q = p;
    while (q < dc) {
        if (starts_with_word_nocase(q, "parameter")) return 1;
        q++;
    }
    return 0;
}

static int source_parameter_line_number(const char *source, const char *name) {
    const char *line = source;
    int line_no = 1;

    while (line && *line) {
        const char *end = strchr(line, '\n');
        char local[4096];
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (len >= sizeof(local)) len = sizeof(local) - 1;
        memcpy(local, line, len);
        local[len] = '\0';
        if (line_is_parameter_declaration_for_name(local, name)) return line_no;
        line = end ? end + 1 : NULL;
        line_no++;
    }
    return 0;
}

static int copy_repl_shortcut_shape(const char **p_in, char *shape, size_t shape_size) {
    const char *p = *p_in;
    const char *start;
    int depth = 0;
    size_t len;

    if (shape_size > 0) shape[0] = '\0';
    if (*p != '(') return 1;
    start = p;
    while (*p) {
        if (*p == '(') depth++;
        else if (*p == ')') {
            depth--;
            if (depth == 0) {
                p++;
                len = (size_t)(p - start);
                if (len >= shape_size) return 0;
                memcpy(shape, start, len);
                shape[len] = '\0';
                *p_in = p;
                return 1;
            }
        } else if (*p == '\r' || *p == '\n') {
            return 0;
        }
        p++;
    }
    return 0;
}

static int parse_repl_decl_shortcut(const char *line, const char **keyword_out,
                                    char *name, size_t name_size,
                                    char *shape, size_t shape_size,
                                    const char **rhs_out) {
    const char *p;
    const char *keyword = NULL;

    if (!line) return 0;

    p = line;
    while (*p == ' ' || *p == '\t') p++;

    if (starts_with_word_nocase(p, "let")) keyword = "let";
    else if (starts_with_word_nocase(p, "const")) keyword = "const";
    else if (starts_with_word_nocase(p, "reconst")) keyword = "reconst";
    else return 0;

    p += strlen(keyword);
    if (*p != ' ' && *p != '\t') return 0;
    while (*p == ' ' || *p == '\t') p++;
    if (!copy_repl_shortcut_identifier(&p, name, name_size)) return 0;
    if (!copy_repl_shortcut_shape(&p, shape, shape_size)) return 0;
    while (*p == ' ' || *p == '\t') p++;
    if (*p != '=' || p[1] == '=') return 0;
    *keyword_out = keyword;
    *rhs_out = p + 1;
    return 1;
}

static void build_repl_decl_shortcut_line(char *out, size_t out_size, const char *keyword,
                                          const char *name, const char *decl,
                                          const char *shape, const char *rhs,
                                          const char *leading, size_t leading_len) {
    int is_const = strcmp(keyword, "const") == 0 || strcmp(keyword, "reconst") == 0;

    if (leading_len >= out_size) {
        if (out_size > 0) out[0] = '\0';
        return;
    }
    memcpy(out, leading, leading_len);
    if (is_const) {
        snprintf(out + leading_len, out_size - leading_len,
                 "%s, parameter :: %s%s = %s", decl, name, shape ? shape : "", skip_space(rhs));
    } else {
        if (shape && shape[0]) {
            snprintf(out + leading_len, out_size - leading_len,
                     "%s :: %s%s\n%.*s%s = %s", decl, name, shape,
                     (int)leading_len, leading, name, skip_space(rhs));
            out[out_size - 1] = '\0';
            return;
        }
        snprintf(out + leading_len, out_size - leading_len,
                 "%s :: %s\n%.*s%s = %s", decl, name, (int)leading_len, leading, name, skip_space(rhs));
    }
    out[out_size - 1] = '\0';
}

static int rewrite_repl_let_const_shortcut(char *line, size_t line_size, const char *source) {
    const char *p;
    const char *rhs;
    const char *keyword = NULL;
    char name[256];
    char shape[256];
    char decl[256];
    char rewritten[4096];
    size_t leading_len;

    if (!line || line_size == 0) return 0;

    p = line;
    while (*p == ' ' || *p == '\t') p++;
    leading_len = (size_t)(p - line);

    if (!parse_repl_decl_shortcut(line, &keyword, name, sizeof(name), shape, sizeof(shape), &rhs)) return 0;
    if (strcmp(keyword, "reconst") == 0) return 0;

    if (source_defines_name(source ? source : "", name)) {
        if (strcmp(keyword, "const") == 0) {
            fprintf(stderr, "CONST name '%s' already exists; use reconst %s = ... to replace a parameter\n",
                    name, name);
        } else {
            fprintf(stderr, "LET variable '%s' already exists; use assignment: %s = ...\n",
                    name, name);
        }
        return -1;
    }

    if (!repl_shortcut_decl_type(rhs, decl, sizeof(decl))) {
        fprintf(stderr, "cannot infer type for %s; use an explicit declaration\n", keyword);
        return -1;
    }

    build_repl_decl_shortcut_line(rewritten, sizeof(rewritten), keyword, name, decl, shape,
                                  rhs, line, leading_len);
    snprintf(line, line_size, "%s", rewritten);
    return 1;
}

static int apply_repl_reconst_shortcut(char **buf, size_t *len, size_t *cap, const char *line) {
    const char *rhs;
    const char *keyword = NULL;
    char name[256];
    char shape[256];
    char decl[256];
    char rewritten[4096];
    int line_no;

    if (!parse_repl_decl_shortcut(line, &keyword, name, sizeof(name), shape, sizeof(shape), &rhs)) return 0;
    if (strcmp(keyword, "reconst") != 0) return 0;

    if (!repl_shortcut_decl_type(rhs, decl, sizeof(decl))) {
        fprintf(stderr, "cannot infer type for reconst; use an explicit PARAMETER declaration\n");
        return -1;
    }
    line_no = source_parameter_line_number(*buf ? *buf : "", name);
    if (line_no <= 0) {
        if (source_defines_name(*buf ? *buf : "", name)) {
            fprintf(stderr, "RECONST name '%s' exists but is not a PARAMETER\n", name);
        } else {
            fprintf(stderr, "RECONST name '%s' is not an existing PARAMETER\n", name);
        }
        return -1;
    }
    build_repl_decl_shortcut_line(rewritten, sizeof(rewritten), keyword, name, decl, shape,
                                  rhs, line, (size_t)(skip_space(line) - line));
    if (!replace_source_line(buf, len, cap, line_no, rewritten)) return -1;
    return 1;
}

static int repl_print_rest_is_quoted_format(const char *rest) {
    char quote;
    const char *p;

    if (!rest || (*rest != '\'' && *rest != '"')) return 0;
    quote = *rest;
    p = rest + 1;
    while (*p == ' ' || *p == '\t') p++;
    if (*p != '(') return 0;

    p = rest + 1;
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
    while (*p == ' ' || *p == '\t') p++;
    return (*p == ',' || *p == '\0' || *p == '\r' || *p == '\n');
}

static void rewrite_repl_print_shortcut(char *line, size_t line_size) {
    const char *p;
    const char *rest;
    char rewritten[4096];
    size_t leading_len;

    if (!line || line_size == 0) return;

    p = line;
    while (*p == ' ' || *p == '\t') p++;
    leading_len = (size_t)(p - line);

    if (!starts_with_word_nocase(p, "print")) return;
    rest = p + 5;
    while (*rest == ' ' || *rest == '\t') rest++;
    if (*rest == '\0' || *rest == '\r' || *rest == '\n') return;

    if (*rest == '*' || *rest == '(') return;
    if (repl_print_rest_is_quoted_format(rest)) return;

    if (leading_len >= sizeof(rewritten)) return;
    memcpy(rewritten, line, leading_len);
    snprintf(rewritten + leading_len, sizeof(rewritten) - leading_len,
             "print *, %s", rest);
    rewritten[sizeof(rewritten) - 1] = '\0';
    snprintf(line, line_size, "%s", rewritten);
}

static const char *skip_balanced_parens_repl(const char *p) {
    int depth = 0;
    char quote = '\0';

    if (*p != '(') return p;
    while (*p) {
        if (quote) {
            if (*p == quote) {
                if (p[1] == quote) {
                    p += 2;
                    continue;
                }
                quote = '\0';
            }
        } else if (*p == '\'' || *p == '"') {
            quote = *p;
        } else if (*p == '(') {
            depth++;
        } else if (*p == ')') {
            depth--;
            if (depth == 0) return p + 1;
        } else if (*p == '\n' || *p == '\r') {
            return p;
        }
        p++;
    }
    return p;
}

static int repl_decl_attribute_name(const char *p, size_t len) {
    static const char *attrs[] = {
        "allocatable", "asynchronous", "contiguous", "dimension", "external",
        "intent", "intrinsic", "optional", "parameter", "pointer", "private",
        "protected", "public", "save", "target", "value", "volatile"
    };
    for (size_t i = 0; i < sizeof(attrs) / sizeof(attrs[0]); i++) {
        if (strlen(attrs[i]) == len && strncasecmp(p, attrs[i], len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int rewrite_repl_declaration_colons(char *line, size_t line_size) {
    char rewritten[4096];
    const char *start = line;
    const char *p;
    const char *insert;
    size_t prefix_len;
    size_t n;

    if (!line || strstr(line, "::")) return 0;
    while (*start && isspace((unsigned char)*start)) start++;
    if (*start == '\0' || *start == '!' || *start == '\n' || *start == '\r') return 0;

    p = start;
    if (starts_with_word_nocase(p, "double")) {
        p = skip_space(p + 6);
        if (!starts_with_word_nocase(p, "precision")) return 0;
        p += 9;
    } else if (starts_with_word_nocase(p, "type") || starts_with_word_nocase(p, "class")) {
        p += starts_with_word_nocase(p, "class") ? 5 : 4;
        p = skip_space(p);
        if (*p != '(') return 0;
        p = skip_balanced_parens_repl(p);
    } else if (starts_with_word_nocase(p, "character")) {
        p += 9;
        p = skip_space(p);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    } else if (starts_with_word_nocase(p, "integer")) {
        p += 7;
        p = skip_space(p);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    } else if (starts_with_word_nocase(p, "complex")) {
        p += 7;
        p = skip_space(p);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    } else if (starts_with_word_nocase(p, "logical")) {
        p += 7;
        p = skip_space(p);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    } else if (starts_with_word_nocase(p, "real")) {
        p += 4;
        p = skip_space(p);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    } else {
        return 0;
    }

    for (;;) {
        const char *attr_start;
        const char *attr_end;
        p = skip_space(p);
        if (*p != ',') break;
        attr_start = skip_space(p + 1);
        if (!(isalpha((unsigned char)*attr_start) || *attr_start == '_')) break;
        attr_end = attr_start;
        while (identifier_char((unsigned char)*attr_end)) attr_end++;
        if (!repl_decl_attribute_name(attr_start, (size_t)(attr_end - attr_start))) break;
        p = skip_space(attr_end);
        if (*p == '(') p = skip_balanced_parens_repl(p);
    }

    insert = skip_space(p);
    if (*insert == '\0' || *insert == '\n' || *insert == '\r' || *insert == '!') return 0;
    if (starts_with_word_nocase(insert, "function") ||
        starts_with_word_nocase(insert, "subroutine")) return 0;

    prefix_len = (size_t)(insert - line);
    if (prefix_len + 3 + strlen(insert) + 1 > line_size ||
        prefix_len + 3 + strlen(insert) + 1 > sizeof(rewritten)) {
        return 0;
    }
    memcpy(rewritten, line, prefix_len);
    n = prefix_len;
    memcpy(rewritten + n, ":: ", 3);
    n += 3;
    snprintf(rewritten + n, sizeof(rewritten) - n, "%s", insert);
    snprintf(line, line_size, "%s", rewritten);
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

static int is_trace_assign_immediate_line(const char *line) {
    static const char *non_assignment_words[] = {
        "program", "end", "subroutine", "function", "module", "use",
        "contains", "implicit", "integer", "real", "double", "character",
        "logical", "complex", "type", "if", "then", "else", "elseif",
        "do", "select", "case", "call", "print", "write", "read",
        "allocate", "deallocate", "return", "stop", "exit", "cycle",
        NULL
    };
    const char *p = skip_space(line);
    int i;

    if (*p == '\0' || *p == '\r' || *p == '\n' || *p == '.') return 0;
    if (strstr(p, "::")) return 0;
    if (!contains_assignment(p)) return 0;
    for (i = 0; non_assignment_words[i]; i++) {
        if (starts_with_word_nocase(p, non_assignment_words[i])) {
            return 0;
        }
    }
    return 1;
}

static int g_implicit_typing = 1;
static int g_warnings_enabled = 1;
static int g_time_detail = 0;
static int g_fast_mode = 0;
static int g_specialized_fast_paths = 1;
static int g_line_profile = 0;
static int g_trace_assign = 0;
static int g_check_uninitialized = 0;
static int g_no_logo = 0;
static int g_init_integer_enabled = 0;
static long long g_init_integer_value = 0;
static int g_init_real_enabled = 0;
static double g_init_real_value = 0.0;
static int g_init_character_enabled = 0;
static char g_init_character_value[OFORT_MAX_STRLEN] = "";
static OfortStandardMode g_standard_mode = OFORT_STD_LEGACY;

static OfortInterpreter *create_ofort_interpreter(void) {
    OfortInterpreter *interp = ofort_create();
    if (interp) {
        ofort_set_implicit_typing(interp, g_implicit_typing);
        ofort_set_warnings_enabled(interp, g_warnings_enabled);
        ofort_set_fast_mode(interp, g_fast_mode);
        ofort_set_specialized_fast_paths(interp, g_specialized_fast_paths);
        ofort_set_line_profile_enabled(interp, g_line_profile);
        ofort_set_trace_assign(interp, g_trace_assign);
        ofort_set_strict_uninitialized(interp, g_check_uninitialized);
        ofort_set_init_integer(interp, g_init_integer_enabled, g_init_integer_value);
        ofort_set_init_real(interp, g_init_real_enabled, g_init_real_value);
        ofort_set_init_character(interp, g_init_character_enabled, g_init_character_value);
        ofort_set_standard_mode(interp, g_standard_mode);
    }
    return interp;
}

static OfortInterpreter *create_repl_interpreter(void) {
    OfortInterpreter *interp = create_ofort_interpreter();
    if (interp) {
        ofort_set_live_stdout(interp, 1);
        ofort_set_strict_uninitialized(interp, 1);
    }
    return interp;
}

static int warnings_include_line(const char *warnings, int line) {
    char needle[64];
    if (!warnings || line <= 0) return 0;
    snprintf(needle, sizeof(needle), "line %d:", line);
    return strstr(warnings, needle) != NULL;
}

static int repl_preflight_check_source(const char *source, const char *footer, int latest_line) {
    char *effective = NULL;
    OfortInterpreter *checker = NULL;
    int rc;
    const char *error;

    if (source_indent_level(source ? source : "") > 0) {
        return 0;
    }

    effective = make_effective_source(source ? source : "", footer);
    if (!effective) {
        fprintf(stderr, "failed to prepare source for interactive check\n");
        return -1;
    }

    checker = create_ofort_interpreter();
    if (!checker) {
        free(effective);
        fprintf(stderr, "failed to create Fortran interpreter\n");
        return -1;
    }

    ofort_set_trace_assign(checker, 0);
    rc = ofort_check(checker, effective);
    if (rc != 0) {
        error = ofort_get_error(checker);
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "interactive check failed");
    } else {
        const char *warnings = ofort_get_warnings(checker);
        if (warnings_include_line(warnings, latest_line)) {
            fputs(warnings, stderr);
        }
    }

    ofort_destroy(checker);
    free(effective);
    return rc;
}

static int execute_source_text(const char *text, int print_expr_statements, int suppress_output,
                               int command_argc, char **command_args, double setup_start,
                               const SourceMap *source_map) {
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
    ofort_set_live_stdout(interp, ISATTY(FILENO(stdin)) && ISATTY(FILENO(stdout)));

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
        print_source_mapped_error(error, source_map);
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
    char *source = read_source_file(source_path);
    FILE *fp;
    OfortInterpreter *interp;
    int rc;

    if (!source) {
        return 2;
    }
    normalize_newlines(source);
    if (!validate_source_file_terminal_end(source_path, source)) {
        free(source);
        return 1;
    }
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

static int check_ofort_file(const char *source_path, int quiet, int label_failures) {
    double setup_start = monotonic_seconds();
    char *source = read_source_file(source_path);
    OfortInterpreter *interp;
    int rc;
    double setup_elapsed;

    if (!source) {
        return 2;
    }
    normalize_newlines(source);
    if (!validate_source_file_terminal_end(source_path, source)) {
        free(source);
        return 1;
    }
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
    if (rc == 0 && !quiet) {
        printf("ofort check passed\n");
    } else if (rc != 0) {
        const char *error = ofort_get_error(interp);
        if (label_failures) {
            fprintf(stderr, "%s:\n", source_path);
        }
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "ofort check failed");
        if (label_failures) {
            fprintf(stderr, "\n");
        }
    }

    ofort_destroy(interp);
    free(source);
    return rc == 0 ? 0 : 1;
}

static int run_each_file(const char *const *paths, int npaths, int limit, int max_fail, int syntax_check,
                         int command_argc, char **command_args, int time_operation,
                         int quiet) {
    int failures = 0;
    int checked = 0;
    int max_to_check = npaths;
    int stopped_by_max_fail = 0;
    double batch_start = monotonic_seconds();
    const char **failed_paths;

    if (limit >= 0 && limit < max_to_check) {
        max_to_check = limit;
    }

    failed_paths = (const char **)calloc((size_t)(max_to_check > 0 ? max_to_check : 1), sizeof(*failed_paths));

    if (!failed_paths) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }

    for (int i = 0; i < max_to_check; i++) {
        int rc;
        double start = monotonic_seconds();
        if (!quiet && i > 0) {
            printf("\n");
        }
        if (!quiet) {
            printf("==> %s\n", paths[i]);
            fflush(stdout);
        }

        if (syntax_check) {
            rc = check_ofort_file(paths[i], quiet, quiet);
        } else {
            char *source = read_source_file(paths[i]);
            if (!source) {
                rc = 2;
            } else if (!validate_source_file_terminal_end(paths[i], source)) {
                rc = 1;
                free(source);
            } else {
                rc = execute_source_text(source, 0, 0, command_argc, command_args, start, NULL);
                free(source);
            }
        }
        if (time_operation && !quiet && !g_time_detail) {
            print_elapsed_time(start);
        }
        if (rc != 0) {
            failed_paths[failures] = paths[i];
            failures++;
            if (max_fail > 0 && failures >= max_fail) {
                stopped_by_max_fail = 1;
                checked++;
                break;
            }
        }
        checked++;
    }

    if (!quiet || failures > 0) {
        printf("\n");
    }
    if (stopped_by_max_fail) {
        printf("stopped after %d failures\n", failures);
    }
    printf("checked %d files: %d passed, %d failed\n", checked, checked - failures, failures);
    if (failures > 0) {
        printf("\nfailing files:\n");
        for (int i = 0; i < failures; i++) {
            printf("  %s\n", failed_paths[i]);
        }
    }
    if (time_operation && quiet && !g_time_detail) {
        printf("\ntime: %.4f s\n", monotonic_seconds() - batch_start);
    }

    free(failed_paths);
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

static int execute_repl_source_prefix(OfortInterpreter *interp, const char *source,
                                      size_t prefix_len, size_t *executed_len,
                                      int trace_assign_enabled) {
    char *prefix;
    int rc;

    if (!source || prefix_len == 0) {
        if (executed_len) *executed_len = 0;
        return 0;
    }
    prefix = (char *)malloc(prefix_len + 1);
    if (!prefix) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }
    memcpy(prefix, source, prefix_len);
    prefix[prefix_len] = '\0';
    ofort_set_trace_assign(interp, trace_assign_enabled);
    rc = execute_source_text_on_interpreter(interp, prefix, 0, 1, 0, NULL);
    ofort_set_trace_assign(interp, g_trace_assign);
    if (rc == 0 && executed_len) {
        *executed_len = prefix_len;
    }
    free(prefix);
    return rc;
}

static int execute_repl_expression(OfortInterpreter *interp, const char *source,
                                   size_t *executed_len, const char *expr_line) {
    int rc = execute_repl_pending_source(interp, source, executed_len);
    const char *p;
    char *wrapped = NULL;
    if (rc != 0) {
        return rc;
    }
    p = skip_space(expr_line);
    if (isdigit((unsigned char)*p)) {
        size_t len = strlen(expr_line);
        while (len > 0 && (expr_line[len - 1] == '\n' || expr_line[len - 1] == '\r')) {
            len--;
        }
        wrapped = (char *)malloc(len + 4);
        if (!wrapped) {
            fprintf(stderr, "out of memory\n");
            return 2;
        }
        wrapped[0] = '(';
        memcpy(wrapped + 1, expr_line, len);
        wrapped[len + 1] = ')';
        wrapped[len + 2] = '\n';
        wrapped[len + 3] = '\0';
        rc = execute_source_text_on_interpreter(interp, wrapped, 1, 1, 0, NULL);
        free(wrapped);
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

static int run_repl_source_with_compiler(const char *compiler, const char *command,
                                         const char *source, const char *shared_src_path,
                                         char **compiler_args, int n_compiler_args,
                                         double *compile_elapsed,
                                         double *run_elapsed) {
    char src_path[256];
    char exe_path[256];
    char obj_path[256];
    char compile_cmd[2048];
    char run_cmd[1024];
    FILE *fp;
    int rc;
    int compile_only = 0;
    double start;
    int using_shared_source = (shared_src_path && shared_src_path[0] != '\0');

    if (compile_elapsed) *compile_elapsed = 0.0;
    if (run_elapsed) *run_elapsed = 0.0;

#ifdef _WIN32
    if (using_shared_source) snprintf(src_path, sizeof(src_path), "%s", shared_src_path);
    else snprintf(src_path, sizeof(src_path), "ofort_repl_%s_%ld.f90", compiler, (long)GETPID());
    snprintf(exe_path, sizeof(exe_path), "ofort_repl_%s_%ld.exe", compiler, (long)GETPID());
    snprintf(obj_path, sizeof(obj_path), "ofort_repl_%s_%ld.o", compiler, (long)GETPID());
#else
    if (using_shared_source) snprintf(src_path, sizeof(src_path), "%s", shared_src_path);
    else snprintf(src_path, sizeof(src_path), "ofort_repl_%s_%ld.f90", compiler, (long)GETPID());
    snprintf(exe_path, sizeof(exe_path), "ofort_repl_%s_%ld", compiler, (long)GETPID());
    snprintf(obj_path, sizeof(obj_path), "ofort_repl_%s_%ld.o", compiler, (long)GETPID());
#endif

    if (!using_shared_source) {
        fp = fopen(src_path, "wb");
        if (!fp) {
            fprintf(stderr, "%s: could not create temporary source file\n", command);
            return 1;
        }
        if (source && source[0]) {
            fputs(source, fp);
        }
        fclose(fp);
    }

    snprintf(compile_cmd, sizeof(compile_cmd), "%s", compiler);
    if (strcmp(compiler, "ifx") == 0) {
        strcat(compile_cmd, " \"-nologo\"");
    }
    for (int i = 0; i < n_compiler_args; i++) {
        if (strcmp(compiler_args[i], "-c") == 0) {
            compile_only = 1;
        }
        if (strlen(compile_cmd) + strlen(compiler_args[i]) + 4 >= sizeof(compile_cmd)) {
            fprintf(stderr, "%s: compiler command is too long\n", command);
            if (!using_shared_source) remove(src_path);
            return 1;
        }
        strcat(compile_cmd, " \"");
        strcat(compile_cmd, compiler_args[i]);
        strcat(compile_cmd, "\"");
    }
    if (strlen(compile_cmd) + strlen(src_path) + strlen(exe_path) + 16 >= sizeof(compile_cmd)) {
        fprintf(stderr, "%s: compiler command is too long\n", command);
        if (!using_shared_source) remove(src_path);
        return 1;
    }
    strcat(compile_cmd, " \"");
    strcat(compile_cmd, src_path);
    if (compile_only) {
        strcat(compile_cmd, "\" -o \"");
        strcat(compile_cmd, obj_path);
    } else {
        strcat(compile_cmd, "\" -o \"");
        strcat(compile_cmd, exe_path);
    }
    strcat(compile_cmd, "\"");
    start = monotonic_seconds();
    rc = system(compile_cmd);
    if (compile_elapsed) *compile_elapsed += monotonic_seconds() - start;
    if (rc != 0) {
        fprintf(stderr, "%s: compile failed\n", command);
        if (!using_shared_source) remove(src_path);
        remove(exe_path);
        remove(obj_path);
        return 1;
    }
    if (compile_only) {
        if (!using_shared_source) remove(src_path);
        remove(obj_path);
        return 0;
    }

#ifdef _WIN32
    snprintf(run_cmd, sizeof(run_cmd), ".\\%s", exe_path);
#else
    snprintf(run_cmd, sizeof(run_cmd), "./%s", exe_path);
#endif
    start = monotonic_seconds();
    rc = system(run_cmd);
    if (run_elapsed) *run_elapsed += monotonic_seconds() - start;
    if (!using_shared_source) remove(src_path);
    remove(exe_path);
    if (rc != 0) {
        fprintf(stderr, "%s: run failed\n", command);
        return 1;
    }
    return 0;
}

static int run_repl_source_with_ofort(OfortInterpreter **interp, const char *source,
                                      const char *footer, size_t *executed_len,
                                      int fast_mode, int specialized_fast_paths) {
    char *effective = make_effective_source(source ? source : "", footer);
    char *exec_source;
    int rc;

    if (!effective) {
        return 2;
    }
    ofort_destroy(*interp);
    *interp = create_repl_interpreter();
    if (!*interp) {
        fprintf(stderr, "failed to create Fortran interpreter\n");
        free(effective);
        return 2;
    }
    exec_source = copy_string(effective);
    if (!exec_source) {
        free(effective);
        return 2;
    }
    normalize_newlines(exec_source);
    exec_source = maybe_wrap_loose_source(exec_source);
    if (!exec_source) {
        free(effective);
        return 2;
    }
    ofort_reset(*interp);
    ofort_set_print_expr_statements(*interp, 1);
    ofort_set_suppress_output(*interp, 0);
    ofort_set_command_args(*interp, 0, NULL);
    ofort_set_strict_uninitialized(*interp, 1);
    ofort_set_fast_mode(*interp, fast_mode);
    ofort_set_specialized_fast_paths(*interp, specialized_fast_paths);
    ofort_set_live_stdout(*interp, 1);
    rc = ofort_execute(*interp, exec_source);
    if (rc == 0) {
        const char *warnings = ofort_get_warnings(*interp);
        const char *output = ofort_get_output(*interp);
        if (warnings && warnings[0] != '\0') {
            fputs(warnings, stderr);
        }
        if (output && output[0] != '\0') {
            fputs(output, stdout);
        }
    } else {
        const char *error = ofort_get_error(*interp);
        fprintf(stderr, "%s\n", (error && error[0] != '\0') ? error : "Fortran execution failed");
    }
    free(exec_source);
    free(effective);
    if (rc == 0 && executed_len) {
        *executed_len = strlen(source ? source : "");
    }
    return rc == 0 ? 0 : 1;
}

static int parse_repl_ofort_command(const char *segment, char **args, int *nargs) {
    return repl_named_command_args(segment, ".ofort", args, nargs);
}

static int parse_timec_ofort_command(const char *segment, char **args, int *nargs) {
    int parsed = repl_named_command_args(segment, ".ofort", args, nargs);
    if (parsed != 0) return parsed;
    return repl_named_command_args(segment, "ofort", args, nargs);
}

static int run_repl_source_with_ofort_args(OfortInterpreter **interp, const char *command,
                                           char **args, int nargs, const char *source,
                                           const char *footer, size_t *executed_len) {
    int fast_mode = g_fast_mode;
    int specialized_fast_paths = g_specialized_fast_paths;

    for (int i = 0; i < nargs; i++) {
        if (strcmp(args[i], "--fast") == 0) {
            fast_mode = 1;
        } else if (strcmp(args[i], "--no-specialize") == 0) {
            specialized_fast_paths = 0;
        } else {
            fprintf(stderr, "%s: unsupported ofort option '%s'\n", command, args[i]);
            return 1;
        }
    }
    return run_repl_source_with_ofort(interp, source, footer, executed_len,
                                      fast_mode, specialized_fast_paths);
}

static char *trim_command_segment(char *text) {
    char *end;
    text = (char *)skip_space(text ? text : "");
    end = text + strlen(text);
    while (end > text && isspace((unsigned char)end[-1])) {
        *--end = '\0';
    }
    return text;
}

static int parse_repl_compiler_command(const char *segment, const char **command,
                                       const char **compiler, char **args, int *nargs) {
    static const char *compiler_commands[][2] = {
        {".gfortran", "gfortran"},
        {".ifx", "ifx"},
        {".lfortran", "lfortran"},
        {".g95", "g95"}
    };

    for (int ci = 0; ci < 4; ci++) {
        int parsed = repl_named_command_args(segment, compiler_commands[ci][0], args, nargs);
        if (parsed != 0) {
            *command = compiler_commands[ci][0];
            *compiler = compiler_commands[ci][1];
            return parsed;
        }
    }
    return 0;
}

static int parse_timec_compiler_command(const char *segment, const char **command,
                                        const char **compiler, char **args, int *nargs) {
    static const char *compiler_commands[][3] = {
        {".gfortran", "gfortran", "gfortran"},
        {".ifx", "ifx", "ifx"},
        {".lfortran", "lfortran", "lfortran"},
        {".g95", "g95", "g95"}
    };

    for (int ci = 0; ci < 4; ci++) {
        int parsed = repl_named_command_args(segment, compiler_commands[ci][0], args, nargs);
        if (parsed == 0) {
            parsed = repl_named_command_args(segment, compiler_commands[ci][1], args, nargs);
        }
        if (parsed != 0) {
            *command = compiler_commands[ci][0];
            *compiler = compiler_commands[ci][2];
            return parsed;
        }
    }
    return 0;
}

static int run_repl_compiler_command_line(const char *line, OfortInterpreter **interp,
                                          const char *source, const char *footer,
                                          size_t *executed_len, int *handled) {
    char *copy = copy_string(line ? line : "");
    char *segment;
    char *effective = NULL;
    int last_rc = 0;

    *handled = 0;
    if (!copy) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }

    segment = copy;
    while (segment) {
        char *next = strchr(segment, ';');
        char *local;
        char *compiler_args[OFORT_MAX_PARAMS];
        int n_compiler_args = 0;
        const char *command = NULL;
        const char *compiler = NULL;
        int parsed;

        if (next) {
            *next++ = '\0';
        }
        local = trim_command_segment(segment);
        segment = next;
        if (local[0] == '\0') {
            continue;
        }

        parsed = parse_repl_ofort_command(local, compiler_args, &n_compiler_args);
        if (parsed != 0) {
            *handled = 1;
            if (parsed > 0) {
                last_rc = run_repl_source_with_ofort_args(interp, ".ofort",
                                                          compiler_args,
                                                          n_compiler_args,
                                                          source, footer,
                                                          executed_len);
                free_split_args(compiler_args, n_compiler_args);
            } else {
                last_rc = 1;
            }
            continue;
        }

        parsed = parse_repl_compiler_command(local, &command, &compiler,
                                             compiler_args, &n_compiler_args);
        if (parsed == 0) {
            if (*handled) {
                fprintf(stderr, "expected compiler command after ';': %s\n", local);
                last_rc = 1;
            }
            break;
        }

        *handled = 1;
        if (parsed < 0) {
            last_rc = 1;
            break;
        }
        if (!effective) {
            effective = make_save_source(source ? source : "", footer);
            if (!effective) {
                free_split_args(compiler_args, n_compiler_args);
                free(copy);
                return 2;
            }
        }

        last_rc = run_repl_source_with_compiler(compiler, command, effective,
                                                NULL,
                                                compiler_args, n_compiler_args,
                                                NULL, NULL);
        free_split_args(compiler_args, n_compiler_args);
    }

    free(effective);
    free(copy);
    return last_rc;
}

static int run_repl_timec_command(const char *line, OfortInterpreter **interp,
                                  const char *source, const char *footer,
                                  size_t *executed_len, int *handled) {
    const char *p = skip_space(line);
    char *copy;
    char *segment;
    char *effective = NULL;
    char shared_src_path[256];
    int have_shared_src = 0;
    int repeat_count = 1;
    int last_rc = 0;

    *handled = 0;
    if (!command_starts_with(p, ".timec")) {
        return 0;
    }
    *handled = 1;
    p = skip_space(p + 6);
    if (isdigit((unsigned char)*p)) {
        char *endptr;
        long count = strtol(p, &endptr, 10);
        if (endptr == p || count < 1 || count > 1000000) {
            fprintf(stderr, ".timec count must be a positive integer\n");
            return 1;
        }
        repeat_count = (int)count;
        p = skip_space(endptr);
    }
    if (*p == '\0' || *p == '\n' || *p == '\r') {
        fprintf(stderr, "usage: .timec [n] .ofort ; .gfortran [options] ; .ifx [options]\n");
        return 1;
    }

    copy = copy_string(p);
    if (!copy) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }
    snprintf(shared_src_path, sizeof(shared_src_path), "ofort_repl_timec_%ld.f90", (long)GETPID());

    printf("%-28s %10s %10s %10s %8s\n", "command", "compile_s", "run_s", "total_s", "status");
    segment = copy;
    while (segment) {
        char *next = strchr(segment, ';');
        char *local;
        double compile_total = 0.0;
        double run_total = 0.0;
        double total = 0.0;
        int is_ofort_command = 0;
        int status = 0;

        if (next) {
            *next++ = '\0';
        }
        local = trim_command_segment(segment);
        segment = next;
        if (local[0] == '\0') {
            continue;
        }

        for (int r = 0; r < repeat_count; r++) {
            double start = monotonic_seconds();
            {
                char *ofort_args[OFORT_MAX_PARAMS];
                int n_ofort_args = 0;
                int ofort_parsed = parse_timec_ofort_command(local, ofort_args, &n_ofort_args);
                if (ofort_parsed != 0) {
                    is_ofort_command = 1;
                    if (ofort_parsed > 0) {
                        status = run_repl_source_with_ofort_args(interp, ".ofort",
                                                                 ofort_args,
                                                                 n_ofort_args,
                                                                 source, footer,
                                                                 executed_len);
                        free_split_args(ofort_args, n_ofort_args);
                    } else {
                        status = 1;
                    }
                    run_total += monotonic_seconds() - start;
                    total = run_total;
                    if (status != 0) break;
                    continue;
                }
            }
            {
                char *compiler_args[OFORT_MAX_PARAMS];
                int n_compiler_args = 0;
                const char *command = NULL;
                const char *compiler = NULL;
                int parsed = parse_timec_compiler_command(local, &command, &compiler,
                                                          compiler_args, &n_compiler_args);
                if (parsed == 0) {
                    fprintf(stderr, "expected compiler command in .timec: %s\n", local);
                    status = 1;
                    break;
                }
                if (parsed < 0) {
                    status = 1;
                    break;
                }
                if (!effective) {
                    effective = make_save_source(source ? source : "", footer);
                    if (!effective) {
                        free_split_args(compiler_args, n_compiler_args);
                        if (have_shared_src) remove(shared_src_path);
                        free(copy);
                        return 2;
                    }
                }
                if (!have_shared_src) {
                    FILE *fp = fopen(shared_src_path, "wb");
                    if (!fp) {
                        fprintf(stderr, ".timec: could not create temporary source file\n");
                        free_split_args(compiler_args, n_compiler_args);
                        free(effective);
                        free(copy);
                        return 1;
                    }
                    if (effective[0]) fputs(effective, fp);
                    fclose(fp);
                    have_shared_src = 1;
                }
                {
                    double compile_elapsed = 0.0;
                    double run_elapsed = 0.0;
                status = run_repl_source_with_compiler(compiler, command, effective,
                                                       shared_src_path,
                                                       compiler_args, n_compiler_args,
                                                       &compile_elapsed, &run_elapsed);
                    compile_total += compile_elapsed;
                    run_total += run_elapsed;
                }
                free_split_args(compiler_args, n_compiler_args);
                total += monotonic_seconds() - start;
                if (status != 0) break;
                continue;
            }
        }

        if (is_ofort_command) {
            printf("%-28s %10s %10.4f %10.4f %8s\n", local,
                   "-",
                   repeat_count > 0 ? run_total / repeat_count : run_total,
                   repeat_count > 0 ? total / repeat_count : total,
                   status == 0 ? "ok" : "failed");
        } else {
            printf("%-28s %10.4f %10.4f %10.4f %8s\n", local,
                   repeat_count > 0 ? compile_total / repeat_count : compile_total,
                   repeat_count > 0 ? run_total / repeat_count : run_total,
                   repeat_count > 0 ? total / repeat_count : total,
                   status == 0 ? "ok" : "failed");
        }
        if (status != 0 && last_rc == 0) {
            last_rc = status;
        }
    }

    free(effective);
    if (have_shared_src) remove(shared_src_path);
    free(copy);
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
    char *source = read_source_file(path);
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

static int path_is_file(const char *path) {
    struct stat st;
    if (!path || stat(path, &st) != 0) return 0;
    return (st.st_mode & S_IFDIR) == 0;
}

static int path_has_extension(const char *path) {
    const char *slash1;
    const char *slash2;
    const char *base;
    const char *dot;

    if (!path || !path[0]) return 0;
    slash1 = strrchr(path, '\\');
    slash2 = strrchr(path, '/');
    base = slash1 > slash2 ? slash1 + 1 : slash2 ? slash2 + 1 : path;
    dot = strrchr(base, '.');
    return dot && dot != base;
}

static char *resolve_source_path_shortcut(const char *arg) {
    char candidate[2048];

    if (!arg || !arg[0]) return copy_string(arg ? arg : "");
    if (path_is_file(arg) || path_has_extension(arg)) return copy_string(arg);
    if (snprintf(candidate, sizeof(candidate), "%s.f90", arg) >= (int)sizeof(candidate)) {
        return copy_string(arg);
    }
    if (path_is_file(candidate)) return copy_string(candidate);
    if (snprintf(candidate, sizeof(candidate), "%s.F90", arg) >= (int)sizeof(candidate)) {
        return copy_string(arg);
    }
    if (path_is_file(candidate)) return copy_string(candidate);
    return copy_string(arg);
}

static int path_is_absolute(const char *path) {
    if (!path || !path[0]) return 0;
    if (path[0] == '/' || path[0] == '\\') return 1;
    return isalpha((unsigned char)path[0]) && path[1] == ':';
}

static void manifest_dirname(const char *path, char *dir, size_t dir_size) {
    const char *slash1 = strrchr(path, '\\');
    const char *slash2 = strrchr(path, '/');
    const char *slash = slash1 > slash2 ? slash1 : slash2;
    size_t len;

    if (!dir || dir_size == 0) return;
    if (!slash) {
        dir[0] = '\0';
        return;
    }
    len = (size_t)(slash - path + 1);
    if (len >= dir_size) len = dir_size - 1;
    memcpy(dir, path, len);
    dir[len] = '\0';
}

static int path_list_add_manifest(PathList *list, const char *manifest_path) {
    char *text;
    char base_dir[1024];
    char *cursor;

    text = read_file(manifest_path);
    if (!text) return 0;
    normalize_newlines(text);
    manifest_dirname(manifest_path, base_dir, sizeof(base_dir));

    cursor = text;
    while (*cursor) {
        char *line = cursor;
        char *newline = strchr(cursor, '\n');
        char *p = line;
        char *end;

        if (newline) {
            *newline = '\0';
            cursor = newline + 1;
        } else {
            cursor += strlen(cursor);
        }
        while (*p && isspace((unsigned char)*p)) p++;
        end = p + strlen(p);
        while (end > p && isspace((unsigned char)end[-1])) end--;
        *end = '\0';
        if (*p != '\0' && *p != '#' && *p != '!') {
            char full[2048];
            if (path_is_absolute(p) || base_dir[0] == '\0') {
                snprintf(full, sizeof(full), "%s", p);
            } else {
                snprintf(full, sizeof(full), "%s%s", base_dir, p);
            }
            if (!path_list_add(list, full)) {
                free(text);
                return 0;
            }
        }
    }

    free(text);
    return 1;
}

static int add_source_path_arg(PathList *list, const char *arg, int expand_globs) {
    char *resolved;
    int ok;
    if (arg && arg[0] == '@' && arg[1] != '\0') {
        return path_list_add_manifest(list, arg + 1);
    }
    if (expand_globs && has_glob_wildcard(arg)) {
        return 2;
    }
    if (expand_globs || has_glob_wildcard(arg)) {
        return path_list_add(list, arg);
    }
    resolved = resolve_source_path_shortcut(arg);
    if (!resolved) return 0;
    ok = path_list_add(list, resolved);
    free(resolved);
    return ok;
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
    int auto_end_lines[128];
    char auto_end_texts[128][128];
    int auto_end_depth = 0;

    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    if (!g_no_logo) {
        printf("Enter Fortran source.\n");
        printf("Commands: . runs, .ofort/.gfortran/.ifx/.lfortran/.g95 [options] run with selected compiler (-c compiles only for external compilers), .timec [n] .ofort ; .gfortran [options] times compiler runs, .run [n] [-- args] repeats, .time [n] [-- args] times, .runq [n] [-- args] runs and quits, .quit quits and saves, .quit! quits without saving, .save [file] saves, .saveq [file] saves and quits, .clear clears, .prompt text changes the prompt, .del n[:m] deletes lines, .ins n text inserts, .rep n text replaces, .rename old new renames, .group-decl groups simple declarations, .unused lists unused simple declarations, .undecl names removes declarations, .drop-unused removes unused simple declarations, .list lists, .list -n lists without line numbers, .decl lists declarations, .vars [names] lists values, .info [names] lists details, .shapes [names] lists array shapes, .sizes [names] lists array sizes, .stats [names] lists array stats, .load file loads, .load-run file loads/runs. With --trace-assign, top-level assignments run immediately. With --auto-end, block openers insert matching END lines.\n");
    }

    repl_interp = create_repl_interpreter();
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

        fputs(g_repl_prompt, stdout);
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
            last_rc = run_repl_source_with_ofort(&repl_interp, buf ? buf : "", footer,
                                                 &executed_len, g_fast_mode,
                                                 g_specialized_fast_paths);
            if (last_rc == 2) {
                free(buf);
                free(footer);
                return 2;
            }
            continue;
        }

        {
            int timec_handled = 0;
            last_rc = run_repl_timec_command(line, &repl_interp, buf ? buf : "", footer,
                                             &executed_len, &timec_handled);
            if (last_rc == 2) {
                free(buf);
                free(footer);
                return 2;
            }
            if (timec_handled) continue;
        }

        {
            int compiler_command_handled = 0;
            last_rc = run_repl_compiler_command_line(line, &repl_interp,
                                                     buf ? buf : "", footer,
                                                     &executed_len,
                                                     &compiler_command_handled);
            if (last_rc == 2) {
                free(buf);
                free(footer);
                return 2;
            }
            if (compiler_command_handled) continue;
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

        if (set_repl_prompt_from_command(line)) {
            continue;
        }

        if (is_command(line, ".quit!")) {
            free(buf);
            free(footer);
            ofort_destroy(repl_interp);
            return last_rc;
        }

        {
            char save_path[1024];
            int has_path = 0;
            int overwrite = 0;
            int parsed = parse_save_command(line, ".save", save_path, sizeof(save_path),
                                            &has_path, &overwrite);
            if (parsed != 0) {
                if (parsed > 0) {
                    last_rc = has_path ?
                              save_interactive_source_to_path(buf ? buf : "", footer, save_path, overwrite) :
                              save_interactive_source(buf ? buf : "", footer);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            char save_path[1024];
            int has_path = 0;
            int overwrite = 0;
            int parsed = parse_save_command(line, ".saveq", save_path, sizeof(save_path),
                                            &has_path, &overwrite);
            if (parsed != 0) {
                if (parsed > 0) {
                    last_rc = has_path ?
                              save_interactive_source_to_path(buf ? buf : "", footer, save_path, overwrite) :
                              save_interactive_source(buf ? buf : "", footer);
                    if (last_rc == 0) {
                        free(buf);
                        free(footer);
                        ofort_destroy(repl_interp);
                        return 0;
                    }
                } else {
                    last_rc = 1;
                }
                continue;
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
            auto_end_depth = 0;
            ofort_destroy(repl_interp);
            repl_interp = create_repl_interpreter();
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
                        auto_end_depth = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_repl_interpreter();
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
                        auto_end_depth = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_repl_interpreter();
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
                        auto_end_depth = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_repl_interpreter();
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
                        repl_interp = create_repl_interpreter();
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

        if (is_command(line, ".list") || is_command(line, ".list -n")) {
            char *effective = make_effective_source(buf ? buf : "", footer);
            if (!effective) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            if (is_command(line, ".list -n")) {
                list_source_plain(effective);
            } else {
                list_source(effective);
            }
            free(effective);
            continue;
        }

        if (is_command(line, ".group-decl")) {
            if (!group_declarations_in_source(&buf, &len, &cap)) {
                fprintf(stderr, "failed to group declarations\n");
                last_rc = 1;
                continue;
            }
            executed_len = 0;
            ofort_destroy(repl_interp);
            repl_interp = create_repl_interpreter();
            if (!repl_interp) {
                fprintf(stderr, "failed to create Fortran interpreter\n");
                free(buf);
                free(footer);
                return 2;
            }
            last_rc = repl_preflight_check_source(buf ? buf : "", footer,
                                                 source_line_count(buf ? buf : ""));
            continue;
        }

        if (is_command(line, ".unused")) {
            char *effective = make_effective_source(buf ? buf : "", footer);
            if (!effective) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            list_unused_declarations_in_source(effective);
            free(effective);
            continue;
        }

        {
            char *undecl_args[OFORT_MAX_PARAMS];
            int n_undecl_args = 0;
            int parsed = repl_named_command_args(line, ".undecl", undecl_args, &n_undecl_args);
            if (parsed != 0) {
                if (parsed > 0) {
                    if (n_undecl_args == 0) {
                        fprintf(stderr, ".undecl requires one or more names\n");
                        last_rc = 1;
                    } else if (!rewrite_declarations_remove_names(&buf, &len, &cap,
                                                                  undecl_args, n_undecl_args, 0)) {
                        fprintf(stderr, "failed to remove declarations\n");
                        last_rc = 1;
                    } else {
                        executed_len = 0;
                        ofort_destroy(repl_interp);
                        repl_interp = create_repl_interpreter();
                        if (!repl_interp) {
                            fprintf(stderr, "failed to create Fortran interpreter\n");
                            free_split_args(undecl_args, n_undecl_args);
                            free(buf);
                            free(footer);
                            return 2;
                        }
                        last_rc = repl_preflight_check_source(buf ? buf : "", footer,
                                                             source_line_count(buf ? buf : ""));
                    }
                    free_split_args(undecl_args, n_undecl_args);
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        if (is_command(line, ".drop-unused")) {
            if (!rewrite_declarations_remove_names(&buf, &len, &cap, NULL, 0, 1)) {
                fprintf(stderr, "failed to drop unused declarations\n");
                last_rc = 1;
                continue;
            }
            executed_len = 0;
            ofort_destroy(repl_interp);
            repl_interp = create_repl_interpreter();
            if (!repl_interp) {
                fprintf(stderr, "failed to create Fortran interpreter\n");
                free(buf);
                free(footer);
                return 2;
            }
            last_rc = repl_preflight_check_source(buf ? buf : "", footer,
                                                 source_line_count(buf ? buf : ""));
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
                    repl_interp = create_repl_interpreter();
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
                    repl_interp = create_repl_interpreter();
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

        {
            int reconst_rc = apply_repl_reconst_shortcut(&buf, &len, &cap, line);
            if (reconst_rc != 0) {
                if (reconst_rc > 0) {
                    executed_len = 0;
                    ofort_destroy(repl_interp);
                    repl_interp = create_repl_interpreter();
                    if (!repl_interp) {
                        fprintf(stderr, "failed to create Fortran interpreter\n");
                        free(buf);
                        free(footer);
                        return 2;
                    }
                    last_rc = repl_preflight_check_source(buf ? buf : "", footer,
                                                         source_line_count(buf ? buf : ""));
                } else {
                    last_rc = 1;
                }
                continue;
            }
        }

        {
            int shortcut_rc = rewrite_repl_let_const_shortcut(line, sizeof(line), buf ? buf : "");
            if (shortcut_rc < 0) {
                last_rc = 1;
                continue;
            }
        }
        rewrite_repl_print_shortcut(line, sizeof(line));
        rewrite_repl_declaration_colons(line, sizeof(line));
        {
            int rewritten_char_len = rewrite_repl_character_constructor_shortcut(line, sizeof(line));
            if (rewritten_char_len > 0 && g_warnings_enabled) {
                fprintf(stderr,
                        "warning: rewrote mixed-length character constructor as character(len=%d)\n",
                        rewritten_char_len);
            }
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
            int insert_line = auto_end_depth > 0 ? auto_end_lines[auto_end_depth - 1]
                                                 : source_line_count(buf ? buf : "") + 1;
            char *indent_source = NULL;
            int line_indent;
            int assignment_immediate = 0;
            int print_immediate = 0;
            int immediate_execute = 0;
            int declaration_after_execution = (executed_len > 0 && is_repl_declaration_line(line));
            size_t old_len = len;
            size_t old_executed_len = executed_len;
            int old_auto_end_depth = auto_end_depth;
            int old_auto_end_lines[128];
            char old_auto_end_texts[128][128];
            char generated_end[128];
            int has_generated_end = 0;
            int inserted_at;

            memcpy(old_auto_end_lines, auto_end_lines, sizeof(auto_end_lines));
            memcpy(old_auto_end_texts, auto_end_texts, sizeof(auto_end_texts));

            if (auto_end_depth > 0 && line_matches_auto_end(line, auto_end_texts[auto_end_depth - 1])) {
                auto_end_depth--;
                last_rc = 0;
                continue;
            }

            indent_source = source_prefix_before_line(buf ? buf : "", insert_line);
            if (!indent_source) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            line_indent = source_indent_level(indent_source);
            free(indent_source);

            assignment_immediate = (line_indent == 0 && is_trace_assign_immediate_line(line));
            print_immediate = (line_indent == 0 && starts_with_word_nocase(skip_space(line), "print"));
            immediate_execute = assignment_immediate || print_immediate;
            has_generated_end = repl_auto_end_for_line(line, generated_end, sizeof(generated_end));
            if (repl_line_pre_dedent(line) && line_indent > 0) {
                line_indent--;
            }
            inserted_at = insert_line;
            if (!insert_indented_repl_line(&buf, &len, &cap, inserted_at, line, line_indent)) {
                free(buf);
                free(footer);
                ofort_destroy(repl_interp);
                return 2;
            }
            for (int i = 0; i < auto_end_depth; i++) {
                if (auto_end_lines[i] >= inserted_at) auto_end_lines[i]++;
            }
            if (has_generated_end && auto_end_depth < (int)(sizeof(auto_end_lines) / sizeof(auto_end_lines[0]))) {
                int end_line = inserted_at + 1;
                if (!insert_indented_repl_line(&buf, &len, &cap, end_line, generated_end, line_indent)) {
                    free(buf);
                    free(footer);
                    ofort_destroy(repl_interp);
                    return 2;
                }
                for (int i = 0; i < auto_end_depth; i++) {
                    if (auto_end_lines[i] >= end_line) auto_end_lines[i]++;
                }
                auto_end_lines[auto_end_depth] = end_line;
                snprintf(auto_end_texts[auto_end_depth], sizeof(auto_end_texts[auto_end_depth]),
                         "%s", generated_end);
                auto_end_depth++;
            }
            last_rc = repl_preflight_check_source(buf ? buf : "", footer,
                                                 source_line_count(buf ? buf : ""));
            if (last_rc != 0) {
                len = old_len;
                if (buf) buf[len] = '\0';
                executed_len = old_executed_len;
                auto_end_depth = old_auto_end_depth;
                memcpy(auto_end_lines, old_auto_end_lines, sizeof(auto_end_lines));
                memcpy(auto_end_texts, old_auto_end_texts, sizeof(auto_end_texts));
                continue;
            }
            if (declaration_after_execution) {
                executed_len = 0;
                ofort_destroy(repl_interp);
                repl_interp = create_repl_interpreter();
                if (!repl_interp) {
                    fprintf(stderr, "failed to create Fortran interpreter\n");
                    free(buf);
                    free(footer);
                    return 2;
                }
            }
            if (immediate_execute) {
                if (executed_len == 0 && old_len > 0) {
                    last_rc = execute_repl_source_prefix(repl_interp, buf ? buf : "", old_len,
                                                        &executed_len, 0);
                    if (last_rc != 0) {
                        continue;
                    }
                }
                last_rc = execute_repl_pending_source(repl_interp, buf ? buf : "", &executed_len);
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

static int source_path_is_fixed_form(const char *path) {
    const char *slash1;
    const char *slash2;
    const char *base;
    const char *dot;
    char ext[32];
    int i;

    if (g_source_form == SOURCE_FORM_FIXED) return 1;
    if (g_source_form == SOURCE_FORM_FREE) return 0;
    if (!path) return 0;
    slash1 = strrchr(path, '\\');
    slash2 = strrchr(path, '/');
    base = slash1 > slash2 ? slash1 + 1 : slash2 ? slash2 + 1 : path;
    dot = strrchr(base, '.');
    if (!dot) return 0;
    for (i = 0; dot[i] && i < (int)sizeof(ext) - 1; i++) {
        ext[i] = (char)tolower((unsigned char)dot[i]);
    }
    ext[i] = '\0';
    return strcmp(ext, ".f") == 0 || strcmp(ext, ".for") == 0 || strcmp(ext, ".ftn") == 0;
}

static int path_has_fixed_form_extension(const char *path) {
    const char *slash1;
    const char *slash2;
    const char *base;
    const char *dot;
    char ext[32];
    int i;

    if (!path) return 0;
    slash1 = strrchr(path, '\\');
    slash2 = strrchr(path, '/');
    base = slash1 > slash2 ? slash1 + 1 : slash2 ? slash2 + 1 : path;
    dot = strrchr(base, '.');
    if (!dot) return 0;
    for (i = 0; dot[i] && i < (int)sizeof(ext) - 1; i++) {
        ext[i] = (char)tolower((unsigned char)dot[i]);
    }
    ext[i] = '\0';
    return strcmp(ext, ".f") == 0 || strcmp(ext, ".for") == 0 || strcmp(ext, ".ftn") == 0;
}

static char *free_form_save_path(const char *path) {
    const char *slash1;
    const char *slash2;
    const char *base;
    const char *dot;
    size_t stem_len;
    size_t out_len;
    char *out;

    if (!path) return NULL;
    slash1 = strrchr(path, '\\');
    slash2 = strrchr(path, '/');
    base = slash1 > slash2 ? slash1 + 1 : slash2 ? slash2 + 1 : path;
    dot = strrchr(base, '.');
    if (dot && path_has_fixed_form_extension(path)) {
        stem_len = (size_t)(dot - path);
        out_len = stem_len + 4;
        out = (char *)malloc(out_len + 1);
        if (!out) return NULL;
        memcpy(out, path, stem_len);
        memcpy(out + stem_len, ".f90", 5);
        return out;
    }

    out_len = strlen(path) + 9;
    out = (char *)malloc(out_len + 1);
    if (!out) return NULL;
    sprintf(out, "%s.free.f90", path);
    return out;
}

static int save_converted_free_form(const char *path, const char *source) {
    char *out_path;
    FILE *fp;

    if (!path || !source) return 0;
    out_path = free_form_save_path(path);
    if (!out_path) {
        fprintf(stderr, "%s: failed to allocate --save-free path\n", path);
        return 0;
    }
    fp = fopen(out_path, "wb");
    if (!fp) {
        fprintf(stderr, "%s: failed to write --save-free output %s\n", path, out_path);
        free(out_path);
        return 0;
    }
    fputs(source, fp);
    fclose(fp);
    if (!g_quiet) {
        printf("Saved free-form source to %s\n", out_path);
    }
    free(out_path);
    return 1;
}

static char *convert_fixed_source_text(char *source, const char *path) {
    OfortFixedFormOptions opts = {72, 1, 0};
    char *error = NULL;
    char *converted;

    if (!source) return NULL;
    converted = ofort_fixed_to_free(source, path, &opts, &error);
    free(source);
    if (!converted) {
        fprintf(stderr, "%s: %s\n", path ? path : "stdin", error ? error : "fixed-form conversion failed");
        free(error);
        return NULL;
    }
    normalize_newlines(converted);
    return converted;
}

static char *read_source_file(const char *path) {
    char *source = read_file(path);
    if (!source) return NULL;
    normalize_newlines(source);
    if (source_path_is_fixed_form(path)) {
        source = convert_fixed_source_text(source, path);
        if (source && g_save_free_form) {
            save_converted_free_form(path, source);
        }
    }
    return source;
}

static int validate_source_file_terminal_end(const char *path, const char *source) {
    if (source_has_terminal_end(source)) return 1;
    if (has_program_unit_header(source)) return 1;
    fprintf(stderr, "Unexpected end of file in '%s'\n", path ? path : "stdin");
    return 0;
}

static char *read_files_concatenated(const char *const *paths, int npaths, SourceMap *source_map) {
    char *source = NULL;
    size_t len = 0;
    size_t cap = 0;
    int next_line = 1;

    for (int i = 0; i < npaths; i++) {
        char *part = read_source_file(paths[i]);
        int line_count;
        if (!part) {
            free(source);
            return NULL;
        }
        line_count = source_text_line_count(part);
        if (!source_map_add(source_map, paths[i], next_line, line_count)) {
            free(part);
            free(source);
            return NULL;
        }
        if (!append_text(&source, &len, &cap, part)) {
            free(part);
            free(source);
            return NULL;
        }
        free(part);
        next_line += line_count;
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

static int string_eq_nocase(const char *a, const char *b) {
    size_t i = 0;
    if (!a || !b) return 0;
    while (a[i] && b[i]) {
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return 0;
        i++;
    }
    return a[i] == '\0' && b[i] == '\0';
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
    fprintf(stderr, "usage: %s [--version] [--nologo] [--repl] [--prompt text] [--auto-end] [-w] [--quiet] [--std=f2023|--std=legacy] [--fast] [--no-specialize] [--fixed-form|--free-form] [--save-free] [--time|--time-detail] [--profile-lines] [--trace-assign] [--check-uninitialized|--check-uninit] [--init-int value] [--init-real value|nan] [--init-char text] [--implicit-typing|--no-implicit-typing] [file1.f90 [file2.f90 ...]] [-- args...]\n", program);
    fprintf(stderr, "       %s --each [--check] [--quiet] [--limit n] [--max-fail n] [options] file-or-glob [file-or-glob ...] [-- args...]\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing|--no-implicit-typing] --load file.f90\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing|--no-implicit-typing] --load-run file.f90\n", program);
    fprintf(stderr, "       %s [-w] [--fast] [--no-specialize] [--time|--time-detail] [--profile-lines] [--implicit-typing|--no-implicit-typing] --check file.f90\n", program);
    fprintf(stderr, "       %s --check-gfortran file.f90\n", program);
    fprintf(stderr, "       %s < file.f90\n", program);
    fprintf(stderr, "       --version prints the ofort version\n");
    fprintf(stderr, "       --nologo suppresses the interactive startup banner\n");
    fprintf(stderr, "       --repl forces an interactive session, useful when stdin is a pipe\n");
    fprintf(stderr, "       --prompt text sets the interactive prompt text\n");
    fprintf(stderr, "       --auto-end makes the REPL insert matching END lines for block openers\n");
    fprintf(stderr, "       -w suppresses warnings\n");
    fprintf(stderr, "       --quiet suppresses success/progress output but not diagnostics\n");
    fprintf(stderr, "       --std=f2023 rejects known nonstandard extensions; --std=legacy is the default\n");
    fprintf(stderr, "       --fast enables safe interpreter fast paths and suppresses warnings\n");
    fprintf(stderr, "       --no-specialize disables specialized pattern/program fast paths\n");
    fprintf(stderr, "       --time prints elapsed time for the requested operation\n");
    fprintf(stderr, "       --time-detail prints setup, lex, parse, register, execute, and total times\n");
    fprintf(stderr, "       --profile-lines prints elapsed execution time by source line\n");
    fprintf(stderr, "       --trace-assign prints assignment trace diagnostics\n");
    fprintf(stderr, "       --check-uninitialized, --check-uninit rejects reads of declared variables before assignment\n");
    fprintf(stderr, "       --init-int value initializes otherwise uninitialized INTEGER variables to value\n");
    fprintf(stderr, "       --init-real value|nan initializes otherwise uninitialized REAL/DOUBLE variables to value or NaN\n");
    fprintf(stderr, "       --init-char text initializes otherwise uninitialized CHARACTER variables with repeated/truncated text\n");
    fprintf(stderr, "       --fixed-form treats input as fixed source form; --free-form forces free source form\n");
    fprintf(stderr, "       --save-free saves converted fixed-form input beside the source as .f90\n");
    fprintf(stderr, "       --each treats each file or Windows glob match as a separate program\n");
    fprintf(stderr, "       --limit n checks at most n files in --each mode\n");
    fprintf(stderr, "       --max-fail n stops --each mode after n failed files; 0 means no limit\n");
    fprintf(stderr, "       @file reads source file names from a manifest, one path per line\n");
    fprintf(stderr, "       --implicit-typing, --legacy-implicit uses I-N integer/rest real implicit typing (default)\n");
    fprintf(stderr, "       --no-implicit-typing rejects undeclared variables unless declared or covered by IMPLICIT\n");
    fprintf(stderr, "       with no file in a console, start an interactive session\n");
}

static int build_month_number(const char *month) {
    static const char *months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    };

    for (int i = 0; i < 12; i++) {
        if (strcmp(month, months[i]) == 0) {
            return i + 1;
        }
    }
    return 0;
}

static const char *build_compiler_name(void) {
#if defined(__clang__)
    return "clang";
#elif defined(__GNUC__)
    return "gcc";
#elif defined(_MSC_VER)
    return "msvc";
#else
    return "unknown";
#endif
}

static void print_version(void) {
    char month_text[4] = {0};
    int day = 0;
    int year = 0;
    int month = 0;
    int hour = 0;
    int minute = 0;

    if (sscanf(__DATE__, "%3s %d %d", month_text, &day, &year) == 3) {
        month = build_month_number(month_text);
    }
    sscanf(__TIME__, "%d:%d", &hour, &minute);

    if (month > 0 && day > 0 && year > 0) {
        printf("ofort %s (built on %04d-%02d-%02d %02d:%02d by %s %s)\n",
               OFORT_VERSION, year, month, day, hour, minute,
               build_compiler_name(), OFORT_BUILD_FLAGS);
    } else {
        printf("ofort %s (built on %s %s by %s %s)\n",
               OFORT_VERSION, __DATE__, __TIME__,
               build_compiler_name(), OFORT_BUILD_FLAGS);
    }
}

int main(int argc, char **argv) {
    char *source;
    PathList source_paths = {0};
    SourceMap source_map = {0};
    const char *load_path = NULL;
    const char *syntax_check_path = NULL;
    const char *check_path = NULL;
    char **program_args = NULL;
    int program_argc = 0;
    int run_after_load = 0;
    int time_operation = 0;
    int each_mode = 0;
    int each_check = 0;
    int each_limit = -1;
    int each_max_fail = 0;
    int quiet = 0;
    int force_interactive = 0;
    double setup_start = 0.0;
    int i;
    if (ISATTY(FILENO(stdout))) {
        setvbuf(stdout, NULL, _IONBF, 0);
    }
    if (ISATTY(FILENO(stderr))) {
        setvbuf(stderr, NULL, _IONBF, 0);
    }

    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        print_version();
        return 0;
    }

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--each") == 0) {
            each_mode = 1;
            break;
        }
    }

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--implicit-typing") == 0 || strcmp(argv[i], "--legacy-implicit") == 0) {
            g_implicit_typing = 1;
        } else if (strcmp(argv[i], "--no-implicit-typing") == 0) {
            g_implicit_typing = 0;
        } else if (strcmp(argv[i], "-w") == 0) {
            g_warnings_enabled = 0;
        } else if (strcmp(argv[i], "--quiet") == 0) {
            quiet = 1;
            g_quiet = 1;
        } else if (strcmp(argv[i], "--nologo") == 0) {
            g_no_logo = 1;
        } else if (strcmp(argv[i], "--repl") == 0 || strcmp(argv[i], "--interactive") == 0) {
            force_interactive = 1;
        } else if (strcmp(argv[i], "--auto-end") == 0) {
            g_repl_auto_end = 1;
        } else if (strcmp(argv[i], "--prompt") == 0) {
            if (++i >= argc) {
                fprintf(stderr, "--prompt requires text\n");
                path_list_free(&source_paths);
                return 2;
            }
            snprintf(g_repl_prompt, sizeof(g_repl_prompt), "%s", argv[i]);
        } else if (strcmp(argv[i], "--std=f2023") == 0 || strcmp(argv[i], "-std=f2023") == 0 ||
                   strcmp(argv[i], "--std=f2018") == 0 || strcmp(argv[i], "-std=f2018") == 0) {
            g_standard_mode = OFORT_STD_F2023;
        } else if (strcmp(argv[i], "--std=legacy") == 0 || strcmp(argv[i], "-std=legacy") == 0) {
            g_standard_mode = OFORT_STD_LEGACY;
        } else if (strncmp(argv[i], "--std=", 6) == 0 || strncmp(argv[i], "-std=", 5) == 0) {
            fprintf(stderr, "unsupported standard mode '%s'\n", argv[i]);
            print_usage(argv[0]);
            path_list_free(&source_paths);
            return 2;
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
        } else if (strcmp(argv[i], "--trace-assign") == 0) {
            g_trace_assign = 1;
            g_specialized_fast_paths = 0;
        } else if (strcmp(argv[i], "--check-uninitialized") == 0 ||
                   strcmp(argv[i], "--check-uninit") == 0) {
            g_check_uninitialized = 1;
        } else if (strcmp(argv[i], "--init-int") == 0) {
            char *endptr;
            long long parsed;
            if (++i >= argc) {
                fprintf(stderr, "--init-int requires an integer value\n");
                path_list_free(&source_paths);
                return 2;
            }
            parsed = strtoll(argv[i], &endptr, 10);
            if (endptr == argv[i] || *endptr != '\0') {
                fprintf(stderr, "--init-int requires an integer value\n");
                path_list_free(&source_paths);
                return 2;
            }
            g_init_integer_enabled = 1;
            g_init_integer_value = parsed;
        } else if (strcmp(argv[i], "--init-real") == 0) {
            char *endptr;
            double parsed;
            if (++i >= argc) {
                fprintf(stderr, "--init-real requires a real value or nan\n");
                path_list_free(&source_paths);
                return 2;
            }
            if (string_eq_nocase(argv[i], "nan")) {
                parsed = NAN;
            } else {
                parsed = strtod(argv[i], &endptr);
                if (endptr == argv[i] || *endptr != '\0') {
                    fprintf(stderr, "--init-real requires a real value or nan\n");
                    path_list_free(&source_paths);
                    return 2;
                }
            }
            g_init_real_enabled = 1;
            g_init_real_value = parsed;
        } else if (strcmp(argv[i], "--init-char") == 0) {
            if (++i >= argc) {
                fprintf(stderr, "--init-char requires text\n");
                path_list_free(&source_paths);
                return 2;
            }
            g_init_character_enabled = 1;
            snprintf(g_init_character_value, sizeof(g_init_character_value), "%s", argv[i]);
        } else if (strcmp(argv[i], "--fixed-form") == 0) {
            g_source_form = SOURCE_FORM_FIXED;
        } else if (strcmp(argv[i], "--free-form") == 0) {
            g_source_form = SOURCE_FORM_FREE;
        } else if (strcmp(argv[i], "--save-free") == 0) {
            g_save_free_form = 1;
        } else if (strcmp(argv[i], "--each") == 0) {
            each_mode = 1;
        } else if (strcmp(argv[i], "--limit") == 0) {
            char *endptr;
            long parsed_limit;
            if (++i >= argc) {
                fprintf(stderr, "--limit requires a non-negative integer\n");
                path_list_free(&source_paths);
                return 2;
            }
            parsed_limit = strtol(argv[i], &endptr, 10);
            if (endptr == argv[i] || *endptr != '\0' ||
                parsed_limit < 0 || parsed_limit > 2147483647L) {
                fprintf(stderr, "--limit requires a non-negative integer\n");
                path_list_free(&source_paths);
                return 2;
            }
            each_limit = (int)parsed_limit;
        } else if (strcmp(argv[i], "--max-fail") == 0) {
            char *endptr;
            long parsed_max_fail;
            if (++i >= argc) {
                fprintf(stderr, "--max-fail requires a non-negative integer\n");
                path_list_free(&source_paths);
                return 2;
            }
            parsed_max_fail = strtol(argv[i], &endptr, 10);
            if (endptr == argv[i] || *endptr != '\0' ||
                parsed_max_fail < 0 || parsed_max_fail > 2147483647L) {
                fprintf(stderr, "--max-fail requires a non-negative integer\n");
                path_list_free(&source_paths);
                return 2;
            }
            each_max_fail = (int)parsed_max_fail;
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
                load_path = resolve_source_path_shortcut(argv[i]);
            } else if (strcmp(opt, "--load-run") == 0) {
                load_path = resolve_source_path_shortcut(argv[i]);
                run_after_load = 1;
            } else if (strcmp(opt, "--check") == 0) {
                syntax_check_path = resolve_source_path_shortcut(argv[i]);
            } else {
                check_path = resolve_source_path_shortcut(argv[i]);
            }
            if ((strcmp(opt, "--load") == 0 || strcmp(opt, "--load-run") == 0) && !load_path) {
                path_list_free(&source_paths);
                return 2;
            }
            if (strcmp(opt, "--check") == 0 && !syntax_check_path) {
                path_list_free(&source_paths);
                return 2;
            }
            if (strcmp(opt, "--check-gfortran") == 0 && !check_path) {
                path_list_free(&source_paths);
                return 2;
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
            if (each_mode && argv[i][0] == '@' && argv[i][1] != '\0') {
                if (!path_list_add_manifest(&source_paths, argv[i] + 1)) {
                    path_list_free(&source_paths);
                    return 2;
                }
            } else if (each_mode) {
                if (!expand_windows_glob(&source_paths, argv[i])) {
                    path_list_free(&source_paths);
                    return 2;
                }
            } else if (!add_source_path_arg(&source_paths, argv[i], 0)) {
                path_list_free(&source_paths);
                return 2;
            }
        }
    }

    if (!each_mode && each_limit >= 0) {
        fprintf(stderr, "--limit is only valid with --each\n");
        path_list_free(&source_paths);
        return 2;
    }

    if (!each_mode && each_max_fail > 0) {
        fprintf(stderr, "--max-fail is only valid with --each\n");
        path_list_free(&source_paths);
        return 2;
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
        int rc = check_ofort_file(syntax_check_path, quiet, 0);
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
        rc = run_each_file(source_paths.items, source_paths.count, each_limit, each_max_fail, each_check,
                           program_argc, program_args, time_operation, quiet);
        path_list_free(&source_paths);
        return rc;
    }

    if (force_interactive) {
        path_list_free(&source_paths);
        return run_interactive(NULL, 0);
    } else if (source_paths.count > 0) {
        setup_start = monotonic_seconds();
        source = read_files_concatenated(source_paths.items, source_paths.count, &source_map);
    } else if (ISATTY(FILENO(stdin))) {
        path_list_free(&source_paths);
        return run_interactive(NULL, 0);
    } else {
        setup_start = monotonic_seconds();
        source = read_stream(stdin, "stdin");
        if (source) normalize_newlines(source);
        if (source && g_source_form == SOURCE_FORM_FIXED) {
            source = convert_fixed_source_text(source, "stdin");
        }
    }
    if (!source) {
        source_map_free(&source_map);
        path_list_free(&source_paths);
        return 2;
    }
    if (source_paths.count > 0 &&
        !validate_source_file_terminal_end(source_paths.count == 1 ? source_paths.items[0] : "combined source", source)) {
        free(source);
        source_map_free(&source_map);
        path_list_free(&source_paths);
        return 1;
    }
    {
        double start = setup_start > 0.0 ? setup_start : monotonic_seconds();
        int rc = execute_source_text(source, 0, 0, program_argc, program_args, start,
                                     source_paths.count > 0 ? &source_map : NULL);
        if (time_operation && !g_time_detail) print_elapsed_time(start);
        free(source);
        source_map_free(&source_map);
        path_list_free(&source_paths);
        return rc;
    }
}

