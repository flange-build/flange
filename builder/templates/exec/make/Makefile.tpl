CC      ?= gcc
CFLAGS  ?= -Wall -O2
TARGET  := ${name}
SRCS    := src/main.c

.PHONY: all clean install

all: $$(TARGET)

$$(TARGET): $$(SRCS)
	$$(CC) $$(CFLAGS) -o $$@ $$^

install: $$(TARGET)
	install -Dm755 $$(TARGET) $$(DESTDIR)/usr/bin/$$(TARGET)

clean:
	rm -f $$(TARGET)
