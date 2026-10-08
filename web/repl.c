#include "ofort.h"

/* Browser-only adapters: native execution and REPL behavior are unchanged. */
void *ofort_web_repl_create(void) {
    OfortInterpreter *interp = ofort_create();
    if (!interp) return NULL;
    ofort_set_implicit_typing(interp, 0);
    ofort_set_strict_uninitialized(interp, 1);
    ofort_set_print_expr_statements(interp, 1);
    return interp;
}

const char *ofort_web_repl_variables(void *handle) {
    static char info[65536];
    info[0] = '\0';
    if (handle)
        ofort_dump_variable_previews((OfortInterpreter *)handle, info, sizeof(info));
    return info;
}
