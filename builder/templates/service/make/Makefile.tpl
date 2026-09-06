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
	install -Dm644 systemd/${name}.service \
	    $$(DESTDIR)/lib/systemd/system/${name}.service
	install -Dm644 conf/config.yaml \
	    $$(DESTDIR)/etc/${name}/config.yaml

clean:
	rm -f $$(TARGET)
