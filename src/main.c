#include "ofort.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#ifdef _WIN32
#include <io.h>
#define ISATTY(fd) _isatty(fd)
#define FILENO(fp) _fileno(fp)
#else
#include <unistd.h>
#define ISATTY(fd) isatty(fd)
#define FILENO(fp) fileno(fp)
#endif

static void normalize_newlines(char *source);
static char *maybe_wrap_loose_source(char *source);

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

static int execute_source_text(const char *text) {
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

static int run_interactive(void) {
    char line[4096];
    char *buf = NULL;
    size_t len = 0;
    size_t cap = 0;
    int last_rc = 0;

    printf("Enter Fortran source.\n");
    printf("Commands: . runs, .runq runs and quits, .quit quits, .clear clears, .list lists.\n");

    for (;;) {
        fputs("ofort> ", stdout);
        fflush(stdout);

        if (!fgets(line, sizeof(line), stdin)) {
            if (ferror(stdin)) {
                free(buf);
                fprintf(stderr, "failed to read stdin\n");
                return 2;
            }
            break;
        }

        if (is_command(line, ".")) {
            last_rc = execute_source_text(buf ? buf : "");
            continue;
        }

        if (is_command(line, ".runq")) {
            last_rc = execute_source_text(buf ? buf : "");
            free(buf);
            return last_rc;
        }

        if (is_command(line, ".quit")) {
            free(buf);
            return 0;
        }

        if (is_command(line, ".clear")) {
            free(buf);
            buf = NULL;
            len = 0;
            cap = 0;
            continue;
        }

        if (is_command(line, ".list")) {
            list_source(buf ? buf : "");
            continue;
        }

        if (!append_text(&buf, &len, &cap, line)) {
            free(buf);
            return 2;
        }
    }

    if (buf && buf[0] != '\0') {
        last_rc = execute_source_text(buf);
    }

    free(buf);
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
    size_t source_len;
    size_t cap;
    char *wrapped;

    if (has_program_unit_header(source)) {
        return source;
    }

    trim_terminal_bare_end(source);
    source_len = strlen(source);
    cap = source_len + 64;
    wrapped = (char *)malloc(cap);
    if (!wrapped) {
        fprintf(stderr, "out of memory\n");
        free(source);
        return NULL;
    }

    snprintf(wrapped, cap, "program __ofort_main\n%s\nend program __ofort_main\n", source);
    free(source);
    return wrapped;
}

static void print_usage(const char *program) {
    fprintf(stderr, "usage: %s [file.f90]\n", program);
    fprintf(stderr, "       %s < file.f90\n", program);
    fprintf(stderr, "       with no file in a console, type a single . line to run\n");
}

int main(int argc, char **argv) {
    char *source;

    if (argc > 2) {
        print_usage(argv[0]);
        return 2;
    }

    if (argc == 2) {
        source = read_file(argv[1]);
    } else if (ISATTY(FILENO(stdin))) {
        return run_interactive();
    } else {
        source = read_stream(stdin, "stdin");
    }
    if (!source) {
        return 2;
    }
    {
        int rc = execute_source_text(source);
        free(source);
        return rc;
    }
}
