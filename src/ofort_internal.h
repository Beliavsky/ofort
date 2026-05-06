#ifndef OFORT_INTERNAL_H
#define OFORT_INTERNAL_H

#include "ofort.h"

OfortValue make_integer(long long v);
OfortValue make_integer_kind(long long v, int kind);
OfortValue make_integer128(__int128 v);
OfortValue make_real(double v);
OfortValue make_double(double v);
OfortValue make_complex(double re, double im);
OfortValue make_complex_kind(double re, double im, int kind);
OfortValue make_character(const char *s);
OfortValue make_logical(int b);
OfortValue make_void_val(void);

double val_to_real(OfortValue v);
long long val_to_int(OfortValue v);
int val_to_logical(OfortValue v);

void free_value(OfortValue *v);
OfortValue copy_value(OfortValue v);
OfortValue resize_character_value(OfortValue val, int char_len);

#endif
