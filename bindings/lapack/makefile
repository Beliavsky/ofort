FC = gfortran
PYTHON ?= python
FFLAGS ?= -O3
MAKEFILE_PATH := $(subst \,/,$(lastword $(MAKEFILE_LIST)))
BINDIR := $(dir $(MAKEFILE_PATH))
ROOT := $(abspath $(BINDIR)../..)
# Use the local bundled source, or supply LAPACK_LIBS and LAPACK_SOURCE=.
LAPACK_SOURCE ?= $(ROOT)/lapack_d.f90
LAPACK_LIBS ?=
ifneq ($(strip $(LAPACK_SOURCE)),)
# lapack_d.f90 contains real routines; supplement its missing complex solver.
COMPLEX_SOURCES = $(wildcard $(BINDIR)vendor/*.f)
endif
ifeq ($(OS),Windows_NT)
TARGET = $(ROOT)/ofort_lapack_backend.dll
SHARED_FLAGS = -shared -static-libgfortran -static-libgcc -Wl,--stack,16777216
else
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
TARGET = $(ROOT)/libofort_lapack_backend.dylib
SHARED_FLAGS = -dynamiclib -fPIC
else
TARGET = $(ROOT)/libofort_lapack_backend.so
SHARED_FLAGS = -shared -fPIC
endif
endif

.PHONY: all clean prepare-python demo python-demo
all: $(TARGET) $(BINDIR)ofort_lapack_mod.o

$(TARGET): $(BINDIR)ofort_lapack_backend.f90 $(LAPACK_SOURCE) $(COMPLEX_SOURCES)
	$(FC) $(FFLAGS) $(SHARED_FLAGS) $(BINDIR)ofort_lapack_backend.f90 $(LAPACK_SOURCE) $(COMPLEX_SOURCES) $(LAPACK_LIBS) -o $@

$(BINDIR)ofort_lapack_mod.o: $(BINDIR)ofort_lapack_mod.f90
	$(FC) $(FFLAGS) -J$(BINDIR) -c $< -o $@

prepare-python:
	$(PYTHON) $(ROOT)/scripts/prepare_python_lapack.py

demo: all
	$(MAKE) -C $(ROOT)
	$(ROOT)/ofort.exe --fast $(BINDIR)demo_lapack.f90

python-demo: all prepare-python
	$(ROOT)/ofort.exe --fast --time $(BINDIR)python_native.f90 $(ROOT)/xpython.f90

clean:
	rm -f $(TARGET) $(BINDIR)ofort_lapack_mod.o $(BINDIR)ofort_lapack_mod.mod $(BINDIR)python_native.f90
