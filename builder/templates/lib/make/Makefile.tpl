CC      := $$(CROSS_COMPILE)gcc
CFLAGS  ?= -Wall -O2
BUILD_DIR ?= build
LIBRARY := lib${name}.so
TARGET  := $$(BUILD_DIR)/$$(LIBRARY)
SRCS    := src/${name}.c

.PHONY: all clean install

all: $$(TARGET)

$$(TARGET): $$(SRCS)
	mkdir -p $$(BUILD_DIR)
	$$(CC) $$(CPPFLAGS) $$(CFLAGS) -fPIC -Iinclude -shared \
	    -Wl,-soname,$$(LIBRARY).1 -o $$(TARGET).${version} $$^ $$(LDFLAGS)
	ln -sf $$(LIBRARY).${version} $$(TARGET).1
	ln -sf $$(LIBRARY).1 $$(TARGET)

install: $$(TARGET)
	install -Dm755 $$(TARGET).${version} $$(DESTDIR)/usr/lib/$$(LIBRARY).${version}
	ln -sf $$(LIBRARY).${version} $$(DESTDIR)/usr/lib/$$(LIBRARY).1
	ln -sf $$(LIBRARY).1 $$(DESTDIR)/usr/lib/$$(LIBRARY)
	install -Dm644 include/${name}.h $$(DESTDIR)/usr/include/${name}.h

clean:
	rm -f $$(TARGET) $$(TARGET).1 $$(TARGET).${version}
