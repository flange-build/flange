CC      ?= gcc
CFLAGS  ?= -Wall -O2 -fPIC -Iinclude
TARGET  := lib${name}.so
SRCS    := src/${name}.c

.PHONY: all clean install

all: $$(TARGET)

$$(TARGET): $$(SRCS)
	$$(CC) $$(CFLAGS) -shared -Wl,-soname,$$(TARGET).1 -o $$(TARGET).${version} $$^
	ln -sf $$(TARGET).${version} $$(TARGET).1
	ln -sf $$(TARGET).1 $$(TARGET)

install: $$(TARGET)
	install -Dm755 $$(TARGET).${version} $$(DESTDIR)/usr/lib/$$(TARGET).${version}
	ln -sf $$(TARGET).${version} $$(DESTDIR)/usr/lib/$$(TARGET).1
	ln -sf $$(TARGET).1 $$(DESTDIR)/usr/lib/$$(TARGET)
	install -Dm644 include/${name}.h $$(DESTDIR)/usr/include/${name}.h

clean:
	rm -f $$(TARGET) $$(TARGET).1 $$(TARGET).${version}
