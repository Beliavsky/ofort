CC = gcc
CFLAGS ?= -O2 -Wall -Wextra -Iinclude
LDFLAGS ?=
LDLIBS ?= -lm

TARGET = ofort.exe
BUILD_INFO = ofort.build
SOURCES = src/main.c src/ofort.c
HEADERS = include/ofort.h

.PHONY: all clean test gcc clang

all: $(TARGET)

$(TARGET): $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) $(SOURCES) $(LDFLAGS) $(LDLIBS) -o $(TARGET)
	printf "cc=%s\n" "$(CC)" > $(BUILD_INFO)

gcc:
	$(MAKE) --always-make CC=gcc

clang:
	$(MAKE) --always-make CC=clang

test: $(TARGET)
	powershell -NoProfile -Command "'program t'; '  print *, \"ofort works\"'; 'end program t'" | ./$(TARGET)

clean:
	rm -f $(TARGET) $(BUILD_INFO) NUL
