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
	install -Dm644 systemd/$$(TARGET).service \
	    $$(DESTDIR)/lib/systemd/system/$$(TARGET).service
	install -Dm644 conf/config.yaml \
	    $$(DESTDIR)/etc/$$(TARGET)/config.yaml

clean:
	rm -f $$(TARGET)
