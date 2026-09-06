CC      := $$(CROSS_COMPILE)gcc
CFLAGS  ?= -Wall -O2
BUILD_DIR ?= build
TARGET  := $$(BUILD_DIR)/${name}
SRCS    := src/main.c

.PHONY: all clean install

all: $$(TARGET)

$$(TARGET): $$(SRCS)
	mkdir -p $$(BUILD_DIR)
	$$(CC) $$(CPPFLAGS) $$(CFLAGS) -o $$@ $$^ $$(LDFLAGS)

install: $$(TARGET)
	install -Dm755 $$(TARGET) $$(DESTDIR)/usr/bin/${name}

clean:
	rm -f $$(TARGET)
