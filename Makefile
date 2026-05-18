CC = gcc
CFLAGS ?= -O2 -Wall -Wextra -Iinclude
ifeq ($(OS),Windows_NT)
STACK_LDFLAGS ?= -Wl,--stack,16777216
else
STACK_LDFLAGS ?=
endif
LDFLAGS ?= $(STACK_LDFLAGS)
LDLIBS ?= -lm

TARGET = ofort.exe
FIXED2FREE = fixed2free.exe
BUILD_INFO = ofort.build
SOURCES = src/main.c src/ofort.c src/ofort_values.c src/ofort_stats.c src/ofort_fixed_form.c
HEADERS = include/ofort.h include/ofort_stats.h include/ofort_fixed_form.h src/ofort_internal.h

.PHONY: all clean test gcc clang

all: $(TARGET)

$(TARGET): $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) $(SOURCES) $(LDFLAGS) $(LDLIBS) -o $(TARGET)
	printf "cc=%s\n" "$(CC)" > $(BUILD_INFO)

$(FIXED2FREE): tools/fixed2free.c src/ofort_fixed_form.c include/ofort_fixed_form.h
	$(CC) $(CFLAGS) tools/fixed2free.c src/ofort_fixed_form.c $(LDFLAGS) -o $(FIXED2FREE)

gcc:
	$(MAKE) --always-make CC=gcc

clang:
	$(MAKE) --always-make CC=clang

test: $(TARGET)
	powershell -NoProfile -Command "'program t'; '  print *, \"ofort works\"'; 'end program t'" | ./$(TARGET)

clean:
	rm -f $(TARGET) $(FIXED2FREE) $(BUILD_INFO) NUL
