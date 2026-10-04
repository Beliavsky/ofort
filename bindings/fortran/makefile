CC = gcc
FC = gfortran
MAKEFILE_PATH := $(subst \,/,$(lastword $(MAKEFILE_LIST)))
BINDIR := $(dir $(MAKEFILE_PATH))
ROOT := $(abspath $(BINDIR)../..)

CFLAGS ?= -O2 -Wall -Wextra -I$(ROOT)/include
FFLAGS ?= -O2
LDLIBS ?= -lm

TARGET = $(BINDIR)demo_eval.exe
C_OBJECTS = $(BINDIR)ofort.o $(BINDIR)ofort_values.o $(BINDIR)ofort_c_api.o $(BINDIR)ofort_stats.o $(BINDIR)ofort_lapack.o
F_OBJECTS = $(BINDIR)ofort_binding.o $(BINDIR)demo_eval.o
STATS_OBJECTS = $(BINDIR)ofort_stats.o $(BINDIR)ofort_statistics_mod.o

.PHONY: all clean run stats_mod

all: $(TARGET)

$(BINDIR)ofort.o: $(ROOT)/src/ofort.c $(ROOT)/include/ofort.h $(ROOT)/src/ofort_internal.h $(ROOT)/include/ofort_lapack.h $(ROOT)/src/ofort_lapack_runtime.inc
	$(CC) $(CFLAGS) -c $(ROOT)/src/ofort.c -o $@

$(BINDIR)ofort_values.o: $(ROOT)/src/ofort_values.c $(ROOT)/include/ofort.h $(ROOT)/src/ofort_internal.h
	$(CC) $(CFLAGS) -c $(ROOT)/src/ofort_values.c -o $@

$(BINDIR)ofort_c_api.o: $(ROOT)/src/ofort_c_api.c $(ROOT)/include/ofort.h $(ROOT)/include/ofort_c_api.h
	$(CC) $(CFLAGS) -c $(ROOT)/src/ofort_c_api.c -o $@

$(BINDIR)ofort_stats.o: $(ROOT)/src/ofort_stats.c $(ROOT)/include/ofort_stats.h
	$(CC) $(CFLAGS) -c $(ROOT)/src/ofort_stats.c -o $@

$(BINDIR)ofort_lapack.o: $(ROOT)/src/ofort_lapack.c $(ROOT)/include/ofort_lapack.h $(ROOT)/src/ofort_lapack_signatures.inc
	$(CC) $(CFLAGS) -c $(ROOT)/src/ofort_lapack.c -o $@

$(BINDIR)ofort_statistics_mod.o: $(BINDIR)ofort_statistics_mod.f90
	$(FC) $(FFLAGS) -J$(BINDIR) -c $(BINDIR)ofort_statistics_mod.f90 -o $@

$(BINDIR)ofort_binding.o: $(BINDIR)ofort_binding.f90
	$(FC) $(FFLAGS) -J$(BINDIR) -c $(BINDIR)ofort_binding.f90 -o $@

$(BINDIR)demo_eval.o: $(BINDIR)demo_eval.f90 $(BINDIR)ofort_binding.o
	$(FC) $(FFLAGS) -I$(BINDIR) -c $(BINDIR)demo_eval.f90 -o $@

$(TARGET): $(C_OBJECTS) $(F_OBJECTS)
	$(FC) $(FFLAGS) $(C_OBJECTS) $(F_OBJECTS) $(LDLIBS) -o $(TARGET)

run: $(TARGET)
	$(TARGET)

stats_mod: $(STATS_OBJECTS)

clean:
	rm -f $(TARGET) $(C_OBJECTS) $(F_OBJECTS) $(BINDIR)ofort_statistics_mod.o *.mod
