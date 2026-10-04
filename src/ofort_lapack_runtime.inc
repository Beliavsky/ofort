/* Interpreter adapter for the optional LAPACK backend. Included here so
   private interpreter structures remain private to ofort.c. */
static int call_ofort_lapack_subroutine(OfortInterpreter *I, OfortNode *call,
                                       const char *name) {
    int id = ofort_lapack_find(name);
    const OfortLapackRoutine *routine = ofort_lapack_routine(id);
    OfortNode *nodes[OFORT_LAPACK_MAX_ARGS] = {0};
    OfortValue *arrays[OFORT_LAPACK_MAX_ARGS] = {0};
    OfortValue *scalar_targets[OFORT_LAPACK_MAX_ARGS] = {0};
    OfortVar *variables[OFORT_LAPACK_MAX_ARGS] = {0};
    void *args[OFORT_LAPACK_MAX_ARGS] = {0};
    void *owned[OFORT_LAPACK_MAX_ARGS] = {0};
    int integers[OFORT_LAPACK_MAX_ARGS] = {0};
    char characters[OFORT_LAPACK_MAX_ARGS] = {0};
    size_t lengths[OFORT_LAPACK_MAX_ARGS] = {0};
    int count, query = 0, info;
    unsigned writes;
    char error[4096];
    if (!routine) return 0;
    count = (int)strlen(routine->types);
    if (call->n_stmts != count)
        ofort_error(I,"%s requires %d arguments",routine->name,count);
    for (int actual = 0; actual < count; actual++) {
        int target = actual;
        if (call->param_names[actual][0]) {
            target = -1;
            for (int j = 0; j < count; j++)
                if (str_eq_nocase(call->param_names[actual],routine->arguments[j])) target = j;
        }
        if (target < 0 || nodes[target])
            ofort_error(I,"Unknown or duplicate argument in %s",routine->name);
        nodes[target] = call->stmts[actual];
    }
    for (int i = 0; i < count; i++) {
        if (!nodes[i]) ofort_error(I,"Missing argument '%s' in %s",routine->arguments[i],routine->name);
        if (nodes[i]->type == FND_IDENT) {
            variables[i] = find_var(I,nodes[i]->name);
            if (variables[i]) scalar_targets[i] = &variables[i]->val;
        } else if (nodes[i]->type == FND_MEMBER) {
            scalar_targets[i] = member_lvalue(I,nodes[i]);
        }
        char type = routine->types[i];
        if (type == 'i' || type == 'c') {
            if (routine->write_mask & (1u << i)) {
                if (!scalar_targets[i] || scalar_targets[i]->type != FVAL_INTEGER ||
                    (variables[i] && (variables[i]->is_parameter || variables[i]->intent == 1)))
                    ofort_error(I,"%s argument '%s' requires a definable INTEGER scalar",
                                routine->name,routine->arguments[i]);
            } else {
                OfortValue v = eval_node(I,nodes[i]);
                if (type == 'i') {
                    long long number = val_to_int(v);
                    if (v.type != FVAL_INTEGER || number < INT_MIN || number > INT_MAX) {
                        free_value(&v);
                        ofort_error(I,"%s argument '%s' requires a 32-bit integer value",
                                    routine->name,routine->arguments[i]);
                    }
                    integers[i] = (int)number;
                    if (strcmp(routine->arguments[i],"lwork") == 0 && number == -1) query = 1;
                } else {
                    if (v.type != FVAL_CHARACTER || !v.v.s || !v.v.s[0]) {
                        free_value(&v);
                        ofort_error(I,"%s argument '%s' requires a character option",
                                    routine->name,routine->arguments[i]);
                    }
                    characters[i] = v.v.s[0];
                }
                free_value(&v);
            }
            args[i] = type == 'i' ? (void *)&integers[i] : (void *)&characters[i];
        }
    }
    info = ofort_lapack_requirements(id,args,lengths);
    if (info < 0) {
        if (!I->check_mode) {
            int last = count - 1;
            if (variables[last]) set_var(I,nodes[last]->name,make_integer(info));
            else {
                free_value(scalar_targets[last]);
                *scalar_targets[last] = make_integer(info);
                mark_assignment_root_initialized(I,nodes[last]);
            }
        }
        return 1;
    }
    writes = routine->write_mask;
    if (query) {
        writes = 1u << (count - 1);
        for (int i = 0; i < count; i++)
            if (strcmp(routine->arguments[i],"work") == 0) writes |= 1u << i;
    }
    /* Validate all storage before giving native code a pointer. Array sections
       and element sequences are deliberately diagnosed by this initial API. */
    for (int i = 0; i < count; i++) {
        char type = routine->types[i];
        if (type == 'i' || type == 'c') continue;
        arrays[i] = scalar_targets[i];
        OfortValue *v = arrays[i];
        if (!v || v->type != FVAL_ARRAY || !v->v.arr.allocated)
            ofort_error(I,"%s argument '%s' requires an allocated whole array or array component",
                        routine->name,routine->arguments[i]);
        int valid = type == 'I' ? v->v.arr.elem_type == FVAL_INTEGER && v->kind != 8 && v->kind != 16 :
            type == 'Z' ? v->v.arr.elem_type == FVAL_COMPLEX && v->kind == 8 :
            (v->v.arr.elem_type == FVAL_DOUBLE || (v->v.arr.elem_type == FVAL_REAL && v->kind == 8));
        if (!valid) ofort_error(I,"%s argument '%s' has the wrong element type/kind",
                               routine->name,routine->arguments[i]);
        if ((size_t)v->v.arr.len < lengths[i])
            ofort_error(I,"%s argument '%s' needs at least %llu elements; got %d",
                        routine->name,routine->arguments[i],(unsigned long long)lengths[i],v->v.arr.len);
        if ((writes & (1u << i)) && variables[i] &&
            (variables[i]->is_parameter || variables[i]->intent == 1))
            ofort_error(I,"%s argument '%s' is not definable",routine->name,routine->arguments[i]);
        if (!query && (routine->read_mask & (1u << i)) && I->strict_uninitialized &&
            variables[i] && !variables[i]->is_initialized)
            ofort_error(I,"Variable '%s' is used before it is set",variables[i]->name);
    }
    if (I->check_mode) return 1;
    for (int i = 0; i < count; i++) {
        if (!arrays[i]) continue;
        OfortValue *v = arrays[i];
        char type = routine->types[i];
        if (type == 'D' && v->v.arr.real_data && v->v.arr.len > 0) {
            args[i] = v->v.arr.real_data;
            continue;
        }
        size_t length = v->v.arr.len > 0 ? (size_t)v->v.arr.len : 1;
        size_t width = type == 'I' ? sizeof(int) : type == 'Z' ? 2*sizeof(double) : sizeof(double);
        args[i] = owned[i] = calloc(length,width);
        if (!args[i]) {
            for (int j = 0; j < count; j++) free(owned[j]);
            ofort_error(I,"Out of memory preparing native LAPACK arguments");
        }
        for (int j = 0; j < v->v.arr.len; j++) {
            OfortValue element = array_element_value(v,j);
            if (type == 'I') ((int *)args[i])[j] = (int)val_to_int(element);
            else if (type == 'Z') {
                ((double *)args[i])[2*j] = element.v.cx.re;
                ((double *)args[i])[2*j+1] = element.v.cx.im;
            } else ((double *)args[i])[j] = val_to_real(element);
            free_value(&element);
        }
    }
    int status = ofort_lapack_call(id,args,error,sizeof(error));
    if (status == 0) for (int i = 0; i < count; i++) {
        if (!(writes & (1u << i))) continue;
        if (arrays[i]) {
            OfortValue *v = arrays[i];
            if (owned[i]) for (int j = 0; j < v->v.arr.len; j++) {
                OfortValue element = routine->types[i] == 'I' ? make_integer(((int *)args[i])[j]) :
                    routine->types[i] == 'Z' ? make_complex_kind(((double *)args[i])[2*j],
                                                               ((double *)args[i])[2*j+1],8) :
                    make_double(((double *)args[i])[j]);
                if (assign_packed_array_element(v,j,element)) free_value(&element);
                else { free_value(&v->v.arr.data[j]); v->v.arr.data[j] = element; }
            }
            mark_assignment_root_initialized(I,nodes[i]);
        } else if (variables[i]) set_var(I,nodes[i]->name,make_integer(integers[i]));
        else {
            free_value(scalar_targets[i]);
            *scalar_targets[i] = make_integer(integers[i]);
            mark_assignment_root_initialized(I,nodes[i]);
        }
    }
    for (int i = 0; i < count; i++) free(owned[i]);
    if (status != 0) ofort_error(I,"%s",error);
    return 1;
}
